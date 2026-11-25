# CHAIR Mobile Packaging & Android/iOS Setup

`apps/mobile` uses **Expo + Expo Router + TypeScript** with React Native Web support.

## Host Environment Notes (Windows)
- Java JDK 17 is installed.
- Android SDK detected at `C:\Users\nikhil\AppData\Local\Android\Sdk`.
- Before running local Android builds or `adb` device checks:
  ```powershell
  $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
  $env:PATH = "$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\emulator;$env:PATH"
  ```

## Packaging & Distribution Profiles
- Configured in `apps/mobile/eas.json`:
  - `development`: Expo Dev Client (`ios.simulator: true`, internal distribution)
  - `preview`: Internal Android `.apk` build for QA on budget Android devices
  - `production`: Play Store / App Store release (`autoIncrement: true`)
- Web preview fallback (`npx expo start --web`) lets developers and Playwright verify responsive mobile viewports even when an emulator is unavailable.
