; Tauri NSIS installer hooks (PLT-01, PLT-06, PLT-24, LOC-01). The per-user installer needs no admin rights.
;
; Before copying, the installer runs jana-precheck (src/bin/precheck.rs, the same checks every installer uses) with
; the size of the app plus the packs the kit installs, the free space of the target drive and the installer's language:
; an unsupported Windows stops the install with its message, too little disk stops it saying how much is needed and
; how much is free, and a machine below the minimum laptop installs with the notice (PLT-29). The precheck words its
; message from strings.json in the installer's language and hands it over as UTF-16LE in a file, so any locale shows
; right whatever the system's code page.
;
; The uninstaller's first page asks what happens to the students' progress, with PLT-24's two labelled choices; keeping
; it is selected until someone chooses otherwise, and a silent uninstall (an update, a script) keeps it. The agent
; core's uninstall then runs with that choice; the delete choice also runs the shell's `--uninstall-keys`, which
; removes the app's keychain items (Credential Manager) and fallback key files, and removes the app's own data folders.
; Only that choice decides: Tauri's "Delete the application data" box on its confirm page is overridden before the
; uninstall section reads it. Every word shown is a key of strings.json (LOC-01), generated into strings.nsh; the
; `installer-strings` check fails on a word written here.
;
; The app's data and its fallback key folder live in the local application data folder, never the roaming one (a
; roaming profile copies %APPDATA% to other machines; src/data_home.rs). Builds before 2026-10-17 kept both in
; %APPDATA%; the app moves them at its first start, through a staging folder beside the local one. The uninstaller
; also handles a machine where that move never ran or was interrupted: the delete choice clears all three places,
; the keep choice runs the core's keep step on each data folder that exists.
;
; JANA_NEEDED_BYTES is defined by the release job (`release package`) from the bundle manifest and the kit's packs.
; OWNER ACTION: validate the uninstaller page, the keychain step, the overridden Tauri box and the roaming-folder
; branches on the Windows runner before the first public build (makensis does not run in the development pipeline).

!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "${__FILEDIR__}\strings.nsh"

!ifndef JANA_NEEDED_BYTES
  !define JANA_NEEDED_BYTES 0
!endif
!define JANA_PRECHECK "${__FILEDIR__}\..\..\..\..\target\release\jana-precheck.exe"
!define JANA_DATA "$LOCALAPPDATA\app.jana.desktop"
!define JANA_KEYS "$LOCALAPPDATA\jana\keys"
!define JANA_STAGING "$LOCALAPPDATA\app.jana.desktop.jana-migrating"
!define JANA_ROAMING_DATA "$APPDATA\app.jana.desktop"
!define JANA_ROAMING_KEYS "$APPDATA\jana\keys"

!macro NSIS_HOOK_PREINSTALL
  InitPluginsDir
  File "/oname=$PLUGINSDIR\jana-precheck.exe" "${JANA_PRECHECK}"
  ${GetRoot} "$INSTDIR" $R0
  ${DriveSpace} "$R0\" "/D=F /S=M" $R1
  IntOp $R1 $R1 * 1048576
  nsExec::ExecToStack '"$PLUGINSDIR\jana-precheck.exe" --needed-bytes ${JANA_NEEDED_BYTES} --free-bytes $R1 --lang $LANGUAGE --message-file "$PLUGINSDIR\jana-precheck.txt"'
  Pop $R2
  Pop $R3
  StrCpy $R3 ""
  ClearErrors
  FileOpen $R4 "$PLUGINSDIR\jana-precheck.txt" r
  ${IfNot} ${Errors}
    FileReadUTF16LE $R4 $R3
    FileClose $R4
  ${EndIf}
  ${If} $R2 == 2
    MessageBox MB_ICONSTOP|MB_OK "$R3"
    Abort
  ${ElseIf} $R3 != ""
    MessageBox MB_ICONINFORMATION|MB_OK "$R3"
  ${EndIf}
!macroend

; PLT-24: the students' progress page, before Tauri's confirm page.
Var JanaLearnerData
Var JanaKeepChoice
Var JanaDeleteChoice

Function un.JanaLearnerDataPage
  StrCpy $JanaLearnerData "keep"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 12u "$(janaUninstallTitle)"
  ${NSD_CreateLabel} 0 16u 100% 24u "$(janaUninstallQuestion)"
  ${NSD_CreateRadioButton} 0 46u 100% 12u "$(janaUninstallKeep)"
  Pop $JanaKeepChoice
  ${NSD_CreateLabel} 12u 60u 95% 12u "$(janaUninstallKeepHelp)"
  ${NSD_CreateRadioButton} 0 78u 100% 12u "$(janaUninstallDelete)"
  Pop $JanaDeleteChoice
  ${NSD_CreateLabel} 12u 92u 95% 24u "$(janaUninstallDeleteHelp)"
  ${NSD_Check} $JanaKeepChoice
  nsDialogs::Show
FunctionEnd

Function un.JanaLearnerDataLeave
  ${NSD_GetState} $JanaDeleteChoice $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $JanaLearnerData "delete"
  ${Else}
    StrCpy $JanaLearnerData "keep"
  ${EndIf}
FunctionEnd

UninstPage custom un.JanaLearnerDataPage un.JanaLearnerDataLeave

!macro NSIS_HOOK_PREUNINSTALL
  ; Tauri's own box would delete the data folders whatever was chosen above: it is set off here, before the uninstall
  ; section reads it, so only the PLT-24 choice decides.
  StrCpy $DeleteAppDataCheckboxState 0
  ${If} $JanaLearnerData == "delete"
    nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall delete --data-dir "${JANA_DATA}\core"'
    Pop $0
    ${If} ${FileExists} "${JANA_STAGING}\core\*.*"
      nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall delete --data-dir "${JANA_STAGING}\core"'
      Pop $0
    ${EndIf}
    ${If} ${FileExists} "${JANA_ROAMING_DATA}\core\*.*"
      nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall delete --data-dir "${JANA_ROAMING_DATA}\core"'
      Pop $0
    ${EndIf}
    nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --uninstall-keys --keys-dir "${JANA_KEYS}"'
    Pop $0
    ${If} $0 != 0
      DetailPrint "$(janaUninstallKeysFailed)"
    ${EndIf}
    ${If} ${FileExists} "${JANA_ROAMING_KEYS}\*.*"
      nsExec::Exec '"$INSTDIR\${MAINBINARYNAME}.exe" --uninstall-keys --keys-dir "${JANA_ROAMING_KEYS}"'
      Pop $0
      ${If} $0 != 0
        DetailPrint "$(janaUninstallKeysFailed)"
      ${EndIf}
    ${EndIf}
    RmDir /r "${JANA_DATA}"
    RmDir /r "${JANA_STAGING}"
    RmDir /r "${JANA_ROAMING_DATA}"
  ${Else}
    nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall keep --data-dir "${JANA_DATA}\core"'
    Pop $0
    ${If} ${FileExists} "${JANA_STAGING}\core\*.*"
      nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall keep --data-dir "${JANA_STAGING}\core"'
      Pop $0
    ${EndIf}
    ${If} ${FileExists} "${JANA_ROAMING_DATA}\core\*.*"
      nsExec::Exec '"$INSTDIR\agent-core\agent-core.exe" --uninstall keep --data-dir "${JANA_ROAMING_DATA}\core"'
      Pop $0
    ${EndIf}
  ${EndIf}
!macroend
