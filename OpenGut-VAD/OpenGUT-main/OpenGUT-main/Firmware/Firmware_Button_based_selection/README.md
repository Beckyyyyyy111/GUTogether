# Firmware UI Based Selection

- Use this firmware if you want to select modes using the buttons on the PCB. 

## Project Structure

- `src/` - Application source files
- `boards/` - Board overlay files
- `prj.conf` - Zephyr project configuration
- `CMakeLists.txt` - Build configuration

## Quick Start

1. Configure your Zephyr/NCS environment.
2. Build the project from the workspace root:
   ```bash
   west build -b nrf54l15dk_nrf54l15_cpuapp
   ```
3. Flash to the board:
   ```bash
   west flash
   ```

