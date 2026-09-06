# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(OpenGutv1)

target_sources(app PRIVATE
	src/main.c
	src/led.c
	src/PDM.c
	src/Playback.c
	src/SD.c
	src/swicthes.c
)

set(pyocd_target_args "--allow-initial-erase")
