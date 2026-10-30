/* Candidate launch wrapper. Install only after hardware and triangle tests.
 * The original binary must be preserved as /usr/libexec/real/backboardd. */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>

static int flag(const char *args, const char *wanted)
{
    size_t length = strlen(wanted);
    for (const char *p = args; *p;) {
        while (*p == ' ') { p++; }
        size_t n = strcspn(p, " ");
        if (n == length && !strncmp(p, wanted, n)) { return 1; }
        p += n;
    }
    return 0;
}

int main(int argc, char **argv)
{
    (void)argc;
    const char *real = "/usr/libexec/real/backboardd";
    const char *loader = "/citrus/lib/libcitrus-loader.dylib";
    char args[2048] = "";
    size_t length = sizeof(args) - 1;
    if (access(real, X_OK)) { perror("CitrusGL: preserved backboardd absent"); return 127; }
    if (!sysctlbyname("kern.bootargs", args, &length, NULL, 0) &&
        flag(args, "citrusgl=1") && !flag(args, "gl=0") && !access(loader, R_OK)) {
        /* /dev/console is 0622, so the mobile user can write it. Without this
         * launchd gives the daemon /dev/null and the loader/eagl diagnostics
         * are lost. */
        int console = open("/dev/console", O_WRONLY);
        if (console >= 0) {
            dup2(console, 1);
            dup2(console, 2);
            if (console > 2) { close(console); }
        }
        setenv("DYLD_INSERT_LIBRARIES", loader, 1);
    }
    argv[0] = (char *)real;
    execv(real, argv);
    perror("CitrusGL: exec preserved backboardd");
    return 127;
}
