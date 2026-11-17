/*
 * poplaunch.exe: Prince of Persia: The Sands of Time started without its
 * launcher (PrinceOfPersia.EXE, a settings window with a Play button).
 *
 * POP.EXE refuses to run alone ("You must start the game with
 * PrinceOfPersia.EXE"): at its start it creates the mutex "POP_Launcher"
 * and goes on only if that already existed (ERROR_ALREADY_EXISTS), that
 * is if the launcher holds it. This program holds it, starts POP.EXE from
 * its own directory with its own arguments and waits for it, its exit
 * code the game's. bare_app_wine runs it as wine.ini's exe.
 *
 * It also deletes PrinceSM first: the game creates that empty file at its
 * start and deletes it when it quits through its menu. A game ended
 * otherwise (bare_app's quit, F6 held) leaves it, and the next start
 * ("Last execution crashed") asks in a Windows message box whether to use
 * safe mode settings; once that box is closed the game's window no longer
 * has the keyboard.
 *
 * Built by games/pop/prepare.sh with the GO Ultra firmware's llvm-mingw.
 */
#include <windows.h>
#include <string.h>

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR args, int show)
{
	char dir[MAX_PATH], cmd[MAX_PATH + 1024], *slash;
	STARTUPINFOA si = { sizeof(si) };
	PROCESS_INFORMATION pi;
	HANDLE mutex;
	DWORD code = 1, n;

	(void)prev;
	(void)show;
	n = GetModuleFileNameA(inst, dir, sizeof(dir));
	if (!n || n >= sizeof(dir) || !(slash = strrchr(dir, '\\')))
		return 1;
	*slash = '\0';
	wsprintfA(cmd, "%s\\PrinceSM", dir);
	DeleteFileA(cmd);
	mutex = CreateMutexA(NULL, FALSE, "POP_Launcher");
	wsprintfA(cmd, "\"%s\\POP.EXE\"%s%s", dir, *args ? " " : "", args);
	if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
		MessageBoxA(NULL, cmd, "poplaunch: cannot start", MB_ICONERROR);
		return 1;
	}
	WaitForSingleObject(pi.hProcess, INFINITE);
	GetExitCodeProcess(pi.hProcess, &code);
	CloseHandle(pi.hThread);
	CloseHandle(pi.hProcess);
	if (mutex)
		CloseHandle(mutex);
	return (int)code;
}
