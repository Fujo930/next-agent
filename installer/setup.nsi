; NextAgent Windows Installer
!define PRODUCT_NAME "NextAgent"
!define PRODUCT_VERSION "0.2.3"
!define PRODUCT_PUBLISHER "NextAgent"

SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "FileFunc.nsh"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\dist\NextAgent-Setup.exe"
InstallDir "$PROGRAMFILES\NextAgent"
RequestExecutionLevel admin

!define MUI_ABORTWARNING
!define MUI_ICON "..\assets\app.ico"
!define MUI_UNICON "..\assets\app.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\NextAgent.exe"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File "..\dist\NextAgent.exe"
  File "..\assets\app.ico"
  CreateDirectory "$INSTDIR\data"
  WriteUninstaller "$INSTDIR\uninst.exe"
  
  CreateDirectory "$SMPROGRAMS\NextAgent"
  CreateShortCut "$SMPROGRAMS\NextAgent\NextAgent.lnk" "$INSTDIR\NextAgent.exe" "" "$INSTDIR\app.ico"
  CreateShortCut "$SMPROGRAMS\NextAgent\Uninstall NextAgent.lnk" "$INSTDIR\uninst.exe"
  CreateShortCut "$DESKTOP\NextAgent.lnk" "$INSTDIR\NextAgent.exe" "" "$INSTDIR\app.ico"
  
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "DisplayName" "NextAgent"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "NoRepair" 1
  
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\NextAgent.exe"
  Delete "$INSTDIR\app.ico"
  Delete "$INSTDIR\uninst.exe"
  RMDir /r "$INSTDIR\data"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\NextAgent\NextAgent.lnk"
  Delete "$SMPROGRAMS\NextAgent\Uninstall NextAgent.lnk"
  RMDir "$SMPROGRAMS\NextAgent"
  Delete "$DESKTOP\NextAgent.lnk"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NextAgent"
  SetAutoClose true
SectionEnd
