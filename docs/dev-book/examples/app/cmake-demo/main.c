#include <stdio.h>

int main(void)
{
#if defined(__aarch64__)
	puts("cmake-demo: aarch64");
#elif defined(__ARM_ARCH)
	printf("cmake-demo: arm, ARMv%d\n", __ARM_ARCH);
#else
	puts("cmake-demo: host");
#endif
	return 0;
}
