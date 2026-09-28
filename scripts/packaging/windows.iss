#ifndef GxVersion
  #error GxVersion is required
#endif
#ifndef GxPayload
  #error GxPayload is required
#endif
#ifndef GxOutput
  #error GxOutput is required
#endif
#ifndef GxFilename
  #error GxFilename is required
#endif

[Setup]
AppId={{DBB81CDE-31BB-487C-9D03-36C19031CC5D}
AppName=Oh My Zsh GX
AppVersion={#GxVersion}
AppPublisher=GX
AppPublisherURL=https://github.com/gx0404/ohmyzsh
DefaultDirName={localappdata}\Programs\OhMyZshGX
DefaultGroupName=Oh My Zsh GX
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
OutputDir={#GxOutput}
OutputBaseFilename={#GxFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
ChangesAssociations=no
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
UninstallDisplayIcon={app}\bin\gx-zsh.exe
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

[Files]
Source: "{#GxPayload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GX Zsh"; Filename: "{app}\bin\gx-zsh.exe"; WorkingDir: "{%USERPROFILE}"

[Code]
const
  OwnerKey = 'Software\OhMyZshGX';
  FontKey = 'Software\Microsoft\Windows NT\CurrentVersion\Fonts';
  EnvironmentKey = 'Environment';
var
  Conflict, PreviousPath, WrittenPath, PreviousOwner, PreviousInstall: String;
  HadPath, HadOwner, HadInstall, PathWritten: Boolean;
  NewFonts: TArrayOfString;

function CreateFileW(Name: String; Access, Sharing: LongWord; Security: Integer;
  Creation, Attributes: LongWord; Template: Integer): Integer;
  external 'CreateFileW@kernel32.dll stdcall';
function CloseHandle(Handle: Integer): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function AddFontResourceExW(Name: String; Flags: LongWord; Reserved: Integer): Integer;
  external 'AddFontResourceExW@gdi32.dll stdcall';
function RemoveFontResourceExW(Name: String; Flags: LongWord; Reserved: Integer): Boolean;
  external 'RemoveFontResourceExW@gdi32.dll stdcall';
function ExpandEnvironmentStringsW(Source: String; Destination: String; Size: LongWord): LongWord;
  external 'ExpandEnvironmentStringsW@kernel32.dll stdcall';

function ExpandEnvironment(const Value: String): String;
var N: LongWord;
begin
  SetLength(Result, 32768);
  N := ExpandEnvironmentStringsW(Value, Result, 32768);
  if (N > 0) and (N <= 32768) then SetLength(Result, N - 1)
  else Result := Value;
end;

function NormalizeEntry(Value: String): String;
begin
  Value := Trim(Value);
  if (Length(Value) >= 2) and (Value[1] = '"') and (Value[Length(Value)] = '"') then
    Value := Copy(Value, 2, Length(Value) - 2);
  Result := Lowercase(RemoveBackslashUnlessRoot(ExpandEnvironment(Value)));
end;

function NextEntry(var Value: String): String;
var P: Integer;
begin
  P := Pos(';', Value);
  if P = 0 then begin Result := Value; Value := ''; end
  else begin Result := Copy(Value, 1, P - 1); Delete(Value, 1, P); end;
end;

function EntryCount(Value, Entry: String): Integer;
begin
  Result := 0;
  while Value <> '' do
    if NormalizeEntry(NextEntry(Value)) = NormalizeEntry(Entry) then Result := Result + 1;
end;

function ResolvedHerdr: String;
var MachinePath, UserPath, Search, Entry: String;
begin
  Result := '';
  RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', MachinePath);
  RegQueryStringValue(HKCU, EnvironmentKey, 'Path', UserPath);
  Search := MachinePath + ';' + UserPath;
  while Search <> '' do begin
    Entry := ExpandEnvironment(Trim(NextEntry(Search)));
    if (Length(Entry) >= 2) and (Entry[1] = '"') and (Entry[Length(Entry)] = '"') then
      Entry := Copy(Entry, 2, Length(Entry) - 2);
    if (Entry <> '') and FileExists(AddBackslash(Entry) + 'herdr.exe') then begin
      Result := AddBackslash(Entry) + 'herdr.exe'; exit;
    end;
    if (Entry <> '') and (FileExists(AddBackslash(Entry) + 'herdr.cmd') or FileExists(AddBackslash(Entry) + 'herdr.bat')) then begin
      Result := Entry + '\herdr (script)'; exit;
    end;
  end;
end;

function BusyFile(const Directory: String): String;
var Item: TFindRec; Path, Extension: String; Handle: Integer;
begin
  Result := '';
  if not DirExists(Directory) then exit;
  if FindFirst(AddBackslash(Directory) + '*', Item) then begin
    try
      repeat
        if (Item.Name <> '.') and (Item.Name <> '..') then begin
          Path := AddBackslash(Directory) + Item.Name;
          if (Item.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then begin
            Result := 'Unsupported reparse point: ' + Path; exit;
          end;
          if (Item.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
            Result := BusyFile(Path);
            if Result <> '' then exit;
          end else begin
            Extension := Lowercase(ExtractFileExt(Path));
            if ((Extension = '.exe') or (Extension = '.dll')) and
               (NormalizeEntry(Path) <> NormalizeEntry(ExpandConstant('{uninstallexe}'))) then begin
              Handle := CreateFileW(Path, $80000000 or $40000000, 0, 0, 3, 0, 0);
              if Handle = -1 then begin Result := Path; exit; end;
              CloseHandle(Handle);
            end;
          end;
        end;
      until not FindNext(Item);
    finally
      FindClose(Item);
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Directory: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Directory := WizardDirValue;
    if (Length(Directory) > 100) or (Length(Directory) < 4) or
       (Copy(Directory, 1, 2) = '\\') or (Pos(';', Directory) > 0) or
       (Pos(#13, Directory) > 0) or (Pos(#10, Directory) > 0) then Result := False;
    if not Result then
      MsgBox('Choose a local installation path of 4 to 100 characters without semicolons or line breaks. Unicode and spaces are supported. User profiles are stored separately.', mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Busy, ExistingOwner: String; HasOwner: Boolean; Item: TFindRec;
begin
  Result := '';
  if not NextButtonClick(wpSelectDir) then begin Result := 'Unsupported installation path.'; exit; end;
  HasOwner := RegQueryStringValue(HKCU, OwnerKey, 'InstallDir', ExistingOwner);
  if HasOwner and (NormalizeEntry(ExistingOwner) <> NormalizeEntry(ExpandConstant('{app}'))) then begin
    Result := 'Uninstall the existing GX installation before changing its directory. User profile data will be preserved.'; exit;
  end;
  if not HasOwner and FindFirst(ExpandConstant('{app}\*'), Item) then begin
    try
      repeat
        if (Item.Name <> '.') and (Item.Name <> '..') then begin
          Result := 'Refusing to install over an unowned non-empty directory. Select a new empty GX directory.'; exit;
        end;
      until not FindNext(Item);
    finally
      FindClose(Item);
    end;
  end;
  Busy := BusyFile(ExpandConstant('{app}'));
  if Busy <> '' then begin
    Result := 'Close GX Zsh/herdr/MSYS2 sessions and retry. No processes will be terminated. In-use or unsafe file: ' + Busy; exit;
  end;
  Conflict := ResolvedHerdr;
  if (Conflict <> '') and (NormalizeEntry(Conflict) <> NormalizeEntry(ExpandConstant('{app}\bin\herdr.exe'))) then begin
    if WizardSilent then begin
      Result := 'Existing herdr command conflicts: ' + Conflict + '. Resolve it explicitly before unattended installation.'; exit;
    end;
    if MsgBox('An existing herdr command was found:' + #13#10 + Conflict + #13#10 +
      'GX will not replace it or prepend PATH. It may still resolve first after installation. Continue and resolve the conflict yourself?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
      Result := 'Installation cancelled because of the existing herdr command.';
  end;
end;

procedure AddOwnedPath;
var Value, Entry: String;
begin
  Entry := ExpandConstant('{app}\bin');
  HadPath := RegQueryStringValue(HKCU, EnvironmentKey, 'Path', PreviousPath);
  HadOwner := RegQueryStringValue(HKCU, OwnerKey, 'PathEntry', PreviousOwner);
  HadInstall := RegQueryStringValue(HKCU, OwnerKey, 'InstallDir', PreviousInstall);
  if HadOwner and (NormalizeEntry(PreviousOwner) <> NormalizeEntry(Entry)) then
    RaiseException('PATH ownership belongs to a different installation.');
  if EntryCount(PreviousPath, Entry) = 0 then begin
    Value := PreviousPath;
    if (Value <> '') and (Copy(Value, Length(Value), 1) <> ';') then Value := Value + ';';
    WrittenPath := Value + Entry;
    if not RegWriteStringValue(HKCU, OwnerKey, 'PathEntry', Entry) then
      RaiseException('Cannot persist PATH ownership.');
    if not RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', WrittenPath) then
      RaiseException('Cannot update user PATH.');
    PathWritten := True;
  end;
  if not RegWriteStringValue(HKCU, OwnerKey, 'InstallDir', ExpandConstant('{app}')) then
    RaiseException('Cannot persist installation ownership.');
end;

procedure RemoveOwnedPath;
var Owned, Value, Remaining, Entry: String;
begin
  if not RegQueryStringValue(HKCU, OwnerKey, 'PathEntry', Owned) then exit;
  if NormalizeEntry(Owned) <> NormalizeEntry(ExpandConstant('{app}\bin')) then exit;
  RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Value);
  if EntryCount(Value, Owned) = 1 then begin
    Remaining := '';
    while Value <> '' do begin
      Entry := NextEntry(Value);
      if NormalizeEntry(Entry) <> NormalizeEntry(Owned) then begin
        if Remaining <> '' then Remaining := Remaining + ';';
        Remaining := Remaining + Entry;
      end;
    end;
    if not RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', Remaining) then
      RaiseException('Cannot remove the owned user PATH entry.');
  end else Log('PATH entry was removed or duplicated externally; preserving the current PATH.');
  RegDeleteValue(HKCU, OwnerKey, 'PathEntry');
end;

procedure Fonts(Installing: Boolean);
var Item: TFindRec; Path, Key, Existing: String; N: Integer;
begin
  if FindFirst(ExpandConstant('{app}\fonts\*.ttf'), Item) then begin
    try
      repeat
        Path := ExpandConstant('{app}\fonts\') + Item.Name;
        Key := 'OhMyZshGX ' + Item.Name + ' (TrueType)';
        if Installing then begin
          if not RegQueryStringValue(HKCU, FontKey, Key, Existing) then begin
            N := GetArrayLength(NewFonts);
            SetArrayLength(NewFonts, N + 1);
            NewFonts[N] := Item.Name;
            if not RegWriteStringValue(HKCU, OwnerKey + '\Fonts', Key, Path) then RaiseException('Cannot persist font ownership.');
            if not RegWriteStringValue(HKCU, FontKey, Key, Path) then RaiseException('Cannot register user font.');
            if AddFontResourceExW(Path, 0, 0) = 0 then RaiseException('Cannot load user font.');
          end;
        end else if RegQueryStringValue(HKCU, OwnerKey + '\Fonts', Key, Existing) and (Existing = Path) then begin
          if RegQueryStringValue(HKCU, FontKey, Key, Existing) and (Existing = Path) then begin
            RemoveFontResourceExW(Path, 0, 0);
            RegDeleteValue(HKCU, FontKey, Key);
          end;
          RegDeleteValue(HKCU, OwnerKey + '\Fonts', Key);
        end;
      until not FindNext(Item);
    finally
      FindClose(Item);
    end;
  end;
end;

procedure RollbackRegistration;
var Current, Key, Path: String; I: Integer;
begin
  for I := 0 to GetArrayLength(NewFonts) - 1 do begin
    Key := 'OhMyZshGX ' + NewFonts[I] + ' (TrueType)';
    Path := ExpandConstant('{app}\fonts\') + NewFonts[I];
    if RegQueryStringValue(HKCU, FontKey, Key, Current) and (Current = Path) then begin
      RemoveFontResourceExW(Path, 0, 0);
      RegDeleteValue(HKCU, FontKey, Key);
    end;
    if RegQueryStringValue(HKCU, OwnerKey + '\Fonts', Key, Current) and (Current = Path) then
      RegDeleteValue(HKCU, OwnerKey + '\Fonts', Key);
  end;
  if PathWritten then begin
    RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Current);
    if Current = WrittenPath then begin
      if HadPath then RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', PreviousPath)
      else RegDeleteValue(HKCU, EnvironmentKey, 'Path');
    end else begin
      Log('Concurrent PATH edit detected during rollback; preserving it and the ownership record.');
      exit;
    end;
  end;
  if HadOwner then RegWriteStringValue(HKCU, OwnerKey, 'PathEntry', PreviousOwner)
  else RegDeleteValue(HKCU, OwnerKey, 'PathEntry');
  if HadInstall then RegWriteStringValue(HKCU, OwnerKey, 'InstallDir', PreviousInstall)
  else RegDeleteValue(HKCU, OwnerKey, 'InstallDir');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Failure: String;
begin
  if CurStep = ssPostInstall then begin
    try
      AddOwnedPath;
      Fonts(True);
    except
      Failure := GetExceptionMessage;
      RollbackRegistration;
      RaiseException(Failure);
    end;
    Conflict := ResolvedHerdr;
    Log('Persistent PATH resolves herdr to: ' + Conflict);
    if NormalizeEntry(Conflict) <> NormalizeEntry(ExpandConstant('{app}\bin\herdr.exe')) then
      MsgBox('PATH command resolution is not the GX herdr entry point: ' + Conflict + #13#10 +
        'Use the GX Zsh shortcut or the full executable path, and resolve the conflict explicitly. User configurations and existing herdr were not modified.', mbInformation, MB_OK);
  end;
end;

function InitializeUninstall: Boolean;
var Busy: String;
begin
  Busy := BusyFile(ExpandConstant('{app}'));
  Result := Busy = '';
  if not Result then MsgBox('Close all GX sessions and retry. No processes will be terminated: ' + Busy, mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    RemoveOwnedPath;
    Fonts(False);
    RegDeleteValue(HKCU, OwnerKey, 'InstallDir');
    RegDeleteKeyIfEmpty(HKCU, OwnerKey + '\Fonts');
    RegDeleteKeyIfEmpty(HKCU, OwnerKey);
  end;
end;
