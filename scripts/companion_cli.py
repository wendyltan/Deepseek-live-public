"""Stable subprocess entry point for the native companion."""
import os
from pathlib import Path
import sys


ROUTES = {
    "computer-preconsent": ("file", "r676_computer_preconsent.py"),
    "computer-question": ("file", "r675_computer_question.py"),
    "context": ("file", "r677_context_rotation.py"),
    "growth": ("node", "r235_native_growth_review.mjs"),
    "market": ("module", "r674_local_market_access"),
    "memory": ("node", "r308_unified_memory.mjs"),
    "memory-action": ("node", "r32_native_memory_action.mjs"),
    "memory-admin": ("file", "r38_memory_admin.py"),
    "motion-check": ("module", "r82_motion_sync_dry_run"),
    "motion-install": ("module", "r83_motion_usb_install"),
    "motion-plan": ("module", "r72_plan_motion_sync"),
    "motion-prepare": ("module", "r72_prepare_motion_candidate"),
    "persona": ("node", "r310_persona_editor.mjs"),
    "plugins": ("module", "r659_plugin_manager"),
    "screen-monitor": ("module", "r92_screen_monitor"),
    "service": ("file", "r459_service_switches.py"),
    "voice-review": ("file", "r307_voice_review_admin.py"),
    "wake": ("file", "r439_persistent_prewake_control.py"),
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args == ["--help"]:
        print("Usage: companion_cli.py {" + ",".join(sorted(ROUTES | {"connection": None})) + "} ...")
        raise SystemExit(0 if args else 2)

    action, *forward = args
    directory = Path(__file__).resolve().parent
    interpreter = sys.executable
    if action == "connection":
        target = Path.home() / "Library/Application Support/Deepseek-live/companion-native/r109_service_manager.py"
        command = [interpreter, str(target)]
    elif action in ROUTES:
        kind, target = ROUTES[action]
        if kind == "node":
            if not forward:
                raise SystemExit("Missing Node executable")
            interpreter, *forward = forward
        command = [interpreter, str(directory / target)]
        if kind == "module":
            command = [interpreter, "-m", f"scripts.{target}"]
    else:
        raise SystemExit(f"Unknown companion command: {action}")

    # Replace the dispatcher so signals, stdio and the exit status belong to the backend.
    os.execv(interpreter, command + forward)


if __name__ == "__main__":
    main()
