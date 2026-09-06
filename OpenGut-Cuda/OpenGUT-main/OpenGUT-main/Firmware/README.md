## Firmware Options

We provide two firmware versions depending on the researcher’s preferred workflow.

---

### 1. Firmware_UI_based_Selection

This firmware wraps all settings into the UI.

#### Setup & Flashing
- Set up the Zephyr / NCS environment  
  - Recommended: nRF Connect SDK on VS Code  
- Build the firmware  
- Flash using an nRF52840 DK  
  - Connect **Debug Out (DK)** → **Debug In (PCB)**  
- Flash the firmware onto the PCB  

Once flashed, the PCB is ready to use.

#### Usage
1. Insert the SD card into your laptop  
2. Using the provided UI, select:
   - Mode  
   - Sampling rate  
   - Duration  
   - File name  
3. Remove the SD card and insert it into the PCB  
4. Turn ON the PCB  

→ The selected mode will run automatically  

---

### 2. Firmware_Button_based_Selection

This firmware keeps primary settings (sampling rate, file name, etc.) in the UI,  
but allows mode control directly on the PCB using buttons.

#### Setup
- Same flashing process as above  
- Configure settings using the UI  

#### Usage
Once powered ON:

- **Button 1** → Select mode  
  - Current mode is indicated by LEDs:
    - **LED1** → Stereo recording  
    - **LED2** → Loopback  
    - **LED3** → Playback (File A)  
    - **LED4** → Playback (File B)  

- **Button 2** → Start / Stop  

---

### Why Use Button-Based Firmware?

This firmware allows researchers to:
- Quickly switch between modes  
- Avoid removing the SD card repeatedly  
- Test different configurations on the go  
