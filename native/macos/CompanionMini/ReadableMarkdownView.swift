// SPDX-License-Identifier: MIT
// Read-only native Markdown; never load HTML or remote images.
import Foundation
import SwiftUI

struct ReadableBlock: Identifiable {
    enum Kind {
        case title(Int), paragraph, list(String,Int), task(Bool,Int), quote, code(String?), rule
        case table([[AttributedString]])
    }
    let id:Int
    var kind:Kind
    var content:AttributedString
}

private final class R634CachedMarkdownBlocks: NSObject {
    let blocks:[ReadableBlock]
    init(_ blocks:[ReadableBlock]) { self.blocks=blocks }
}
enum ReadableMarkdown {
    // Immutable, read-only Markdown parsed once per exact text. No HTML,
    // network, side effects or cross-session state. NSCache may evict freely.
    private static let cache: NSCache<NSString,R634CachedMarkdownBlocks> = {
        let instance=NSCache<NSString,R634CachedMarkdownBlocks>()
        instance.countLimit=72
        instance.totalCostLimit=6_000_000
        return instance
    }()
    static func parse(_ source:String)->[ReadableBlock] {
        let eligible=source.utf8.count<=12_000
        let key=source as NSString
        if eligible,let hit=cache.object(forKey:key) {return hit.blocks}
        let result=parseUncached(source)
        if eligible {
            cache.setObject(R634CachedMarkdownBlocks(result),forKey:key,
                            cost:source.utf8.count*4)
        }
        return result
    }
    private static func parseUncached(_ source:String)->[ReadableBlock] {
        guard let document=try? AttributedString(markdown:source,
                options:.init(failurePolicy:.returnPartiallyParsedIfPossible,
                              appliesSourcePositionAttributes:true)) else {
            return [ReadableBlock(id:0,kind:.paragraph,content:AttributedString(source))]
        }
        let bytes=Array(source.utf8)
        var lineStarts=[0]
        for (index,byte) in bytes.enumerated() where byte == 10 {lineStarts.append(index+1)}
        let marker=["\u{200B}","\u{2060}","\u{FEFF}"].first{!source.contains($0)}
        var blocks=[ReadableBlock]()
        var positions=[Int:Int]()
        var tablePositions=[Int:Int]()
        var seenListItems=Set<Int>()
        var codeLines=[ClosedRange<Int>]()
        for run in document.runs {
            var part=AttributedString(document[run.range])
            let components=run.presentationIntent?.components ?? []
            let isCode=run.inlinePresentationIntent?.contains(.code) == true || components.contains {
                if case .codeBlock = $0.kind {return true};return false
            }
            if isCode,let position=run.markdownSourcePosition {
                codeLines.append(position.startLine...position.endLine)
            }
            // Repair only literal text whose source bytes exactly match the
            // parsed run. Code, escaped text and link destinations stay intact.
            if !isCode,run.link == nil,let marker,let position=run.markdownSourcePosition,
               position.startLine>0,position.endLine<=lineStarts.count {
                let start=lineStarts[position.startLine-1]+position.startColumn-1
                let end=lineStarts[position.endLine-1]+position.endColumn
                if start>=0,end>=start,end<=bytes.count,
                   let original=String(bytes:bytes[start..<end],encoding:.utf8),
                   original==String(part.characters),original.contains("**") {
                    let protected=original.replacingOccurrences(
                        of:#"(?<![\\*])\*\*([^*\n]+)\*\*(?!\*)"#,
                        with:"**\(marker)$1\(marker)**",options:.regularExpression)
                    if protected != original,
                       var repaired=try? AttributedString(markdown:protected,
                           options:.init(interpretedSyntax:.inlineOnlyPreservingWhitespace,
                                         failurePolicy:.returnPartiallyParsedIfPossible)),
                       let character=marker.first {
                        while let index=repaired.characters.firstIndex(of:character) {
                            repaired.removeSubrange(index..<repaired.characters.index(after:index))
                        }
                        part=repaired
                    }
                }
            }
            guard let components=run.presentationIntent?.components,
                  let leaf=components.first else {
                blocks.append(ReadableBlock(id:-(blocks.count+1),kind:.paragraph,content:part))
                continue
            }
            let table=components.first { if case .table = $0.kind {return true}; return false }
            if let table,case .tableCell(let column)=leaf.kind {
                let row=components.first {
                    if case .tableHeaderRow = $0.kind {return true}
                    if case .tableRow = $0.kind {return true}
                    return false
                }
                guard let row else {continue}
                let rowNumber:Int
                if case .tableRow(let index)=row.kind {rowNumber=index} else {rowNumber=0}
                let position:Int
                if let existing=tablePositions[table.identity] {position=existing}
                else {
                    position=blocks.count
                    tablePositions[table.identity]=position
                    blocks.append(ReadableBlock(id:table.identity,kind:.table([]),content:AttributedString()))
                }
                guard case .table(var rows)=blocks[position].kind else {continue}
                let columnCount:Int
                if case .table(let columns)=table.kind {columnCount=columns.count} else {columnCount=column+1}
                while rows.count<=rowNumber {rows.append(Array(repeating:AttributedString(),count:columnCount))}
                while rows[rowNumber].count<=column {rows[rowNumber].append(AttributedString())}
                rows[rowNumber][column].append(part)
                blocks[position].kind = .table(rows)
                continue
            }
            if let position=positions[leaf.identity] {
                blocks[position].content.append(part)
                continue
            }
            var kind:ReadableBlock.Kind = .paragraph
            switch leaf.kind {
            case .header(let level): kind = .title(level)
            case .codeBlock(let language): kind = .code(language)
            case .thematicBreak: kind = .rule
            default:
                let quoteIndex=components.firstIndex(where:{if case .blockQuote = $0.kind {return true};return false})
                if let listIndex=components.firstIndex(where:{ if case .listItem = $0.kind {return true}; return false }),
                   quoteIndex == nil || listIndex < quoteIndex!,
                   case .listItem(let ordinal)=components[listIndex].kind {
                    let ordered = listIndex+1<components.count && {
                        if case .orderedList = components[listIndex+1].kind {return true};return false
                    }()
                    let depth=components.filter {
                        if case .listItem = $0.kind {return true};return false
                    }.count-1
                    let item=components[listIndex].identity
                    let first=seenListItems.insert(item).inserted
                    kind = .list(first ? (ordered ? "\(ordinal)." : "•") : "",max(0,depth))
                } else if quoteIndex != nil {
                    kind = .quote
                }
            }
            positions[leaf.identity]=blocks.count
            blocks.append(ReadableBlock(id:leaf.identity,kind:kind,content:part))
        }
        for index in blocks.indices {
            guard case .list("•",let depth)=blocks[index].kind else {continue}
            let text=String(blocks[index].content.characters)
            guard text.hasPrefix("[ ] ") || text.hasPrefix("[x] ") || text.hasPrefix("[X] ") else {continue}
            let checked = !text.hasPrefix("[ ] ")
            let start=blocks[index].content.startIndex
            let end=blocks[index].content.characters.index(start,offsetBy:4)
            blocks[index].content.removeSubrange(start..<end)
            blocks[index].kind = .task(checked,depth)
        }
        // Foundation omits footnote definitions; retain them as literal text.
        for (index,line) in source.components(separatedBy:"\n").enumerated() {
            let lineNumber=index+1
            guard !codeLines.contains(where:{$0.contains(lineNumber)}),
                  line.range(of:#"^ {0,3}\[\^[^\]]+\]:"#,options:.regularExpression) != nil else {continue}
            blocks.append(ReadableBlock(id:-(blocks.count+1),kind:.paragraph,content:AttributedString(line)))
        }
        return blocks.isEmpty ? [ReadableBlock(id:0,kind:.paragraph,content:AttributedString(source))] : blocks
    }

    static func blocks(_ source:String)->[(String,String)] {
        parse(source).map { block in
            let text=String(block.content.characters)
            switch block.kind {
            case .title: return ("title",text)
            case .paragraph: return ("paragraph",text)
            case .list(let marker,_): return (marker == "•" ? "bullet" : marker.isEmpty ? "paragraph" : "ordered",marker.isEmpty ? text : marker+" "+text)
            case .task(let checked,_): return (checked ? "task-done" : "task-open",text)
            case .quote: return ("quote",text)
            case .code: return ("code",text)
            case .rule: return ("rule",text)
            case .table(let rows):
                return ("table",rows.map{$0.map{String($0.characters)}.joined(separator:"\u{001F}")}
                                    .joined(separator:"\u{001E}"))
            }
        }
    }
    static func tableRows(_ payload:String)->[[String]] {
        payload.components(separatedBy:"\u{001E}").map{$0.components(separatedBy:"\u{001F}")}
    }
}

struct ReadableMarkdownView: View {
    let source:String
    private var blocks:[ReadableBlock] {ReadableMarkdown.parse(source)}
    var body:some View {
        VStack(alignment:.leading,spacing:11) {
            ForEach(blocks) { block in
                switch block.kind {
                case .title(let level):
                    Text(block.content)
                        .font(.system(size:level<=2 ? 16 : 14,weight:.semibold))
                        .padding(.top,4)
                        .fixedSize(horizontal:false,vertical:true)
                case .paragraph:
                    Text(block.content).font(.system(size:13))
                        .lineSpacing(4).fixedSize(horizontal:false,vertical:true)
                case .list(let marker,let depth):
                    HStack(alignment:.top,spacing:8) {
                        Text(marker).font(.system(size:13,weight:.medium))
                            .frame(minWidth:18,alignment:.trailing)
                        Text(block.content).font(.system(size:13))
                            .lineSpacing(3).fixedSize(horizontal:false,vertical:true)
                    }.padding(.leading,CGFloat(min(depth,4))*18)
                case .task(let checked,let depth):
                    HStack(alignment:.top,spacing:8) {
                        Image(systemName:checked ? "checkmark.square.fill" : "square")
                            .foregroundStyle(checked ? Color.accentColor : Color.secondary)
                            .frame(width:18)
                            .accessibilityLabel(checked ? "已完成" : "未完成")
                        Text(block.content).font(.system(size:13))
                            .lineSpacing(3).fixedSize(horizontal:false,vertical:true)
                    }.padding(.leading,CGFloat(min(depth,4))*18)
                case .quote:
                    Text(block.content).font(.system(size:13))
                        .lineSpacing(4).foregroundStyle(.secondary)
                        .padding(.horizontal,14).padding(.vertical,10)
                        .frame(maxWidth:.infinity,alignment:.leading)
                        .background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:8))
                case .rule:
                    Divider().padding(.vertical,4)
                case .table(let rows):
                    ScrollView(.horizontal) {
                        VStack(alignment:.leading,spacing:0) {
                            ForEach(Array(rows.enumerated()),id:\.offset) { rowIndex,row in
                                HStack(alignment:.top,spacing:0) {
                                    ForEach(Array(row.enumerated()),id:\.offset) { _,cell in
                                        Text(cell).font(.system(size:12,weight:rowIndex==0 ? .semibold : .regular))
                                            .fixedSize(horizontal:false,vertical:true)
                                            .frame(width:130,alignment:.leading)
                                            .padding(.horizontal,10).padding(.vertical,9)
                                            .frame(minHeight:36,alignment:.topLeading)
                                    }
                                }
                                .background(rowIndex==0 ? Color.primary.opacity(0.08) :
                                            (rowIndex.isMultiple(of:2) ? Color.primary.opacity(0.035) : Color.clear))
                            }
                        }
                        .clipShape(RoundedRectangle(cornerRadius:8))
                    }.frame(maxWidth:.infinity,alignment:.leading)
                case .code(let language):
                    VStack(alignment:.leading,spacing:6) {
                        if let language,!language.isEmpty {
                            Text(language).font(.system(size:11,weight:.medium)).foregroundStyle(.secondary)
                        }
                        ScrollView(.horizontal) {
                            Text(block.content).font(.system(size:12,design:.monospaced))
                                .textSelection(.enabled)
                        }
                    }
                    .padding(12).frame(maxWidth:.infinity,alignment:.leading)
                    .background(Color.primary.opacity(0.05),in:RoundedRectangle(cornerRadius:8))
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth:.infinity,alignment:.leading)
        .accessibilityElement(children:.contain)
    }
}
