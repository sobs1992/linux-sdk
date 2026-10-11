/* Minimal program: prints where it runs. */
#include <stdio.h>
#include <sys/utsname.h>

int main(void)
{
	struct utsname u;

	if (uname(&u) != 0) {
		perror("uname");
		return 1;
	}
	printf("Hello from %s: %s, kernel %s\n", u.nodename, u.machine, u.release);
	return 0;
}
