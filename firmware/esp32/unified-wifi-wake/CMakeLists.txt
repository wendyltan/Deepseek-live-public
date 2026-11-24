cmake_minimum_required(VERSION 3.16)
# Version is surfaced in ESP-IDF esp_app_desc and the on-board About page.
# Previous app metadata was just "1" despite the R482 development label.
set(PROJECT_VER "0.2.0")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(dafeiyu_h4_audio_smoke)
