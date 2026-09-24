EqUpdater fonts

EqUpdater supports Friz Quadrata, Arial, and OpenDyslexic.

The installer and runtime automatically import the user's own font archives
without installing them system-wide. They search the EqUpdater project/app
folder and common user folders (Downloads, Desktop, Documents) for:

  friz-quadrata*.zip / friz*.zip
  arial*.zip
  opendyslexic*.zip

Font files are copied into:

  %LOCALAPPDATA%\EqUpdater\fonts

and registered privately for the EqUpdater process on Windows.

Expected family names:
  Friz Quadrata
  Arial
  OpenDyslexic
