/* Standalone Citrus GPU acceptance test. No compositor hooks or screen writes.
 * Render into an imported IOSurface, wait, and check GL and CPU readback.
 * A software renderer or an unshared texture is a failure, never a pass. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurfaceRef.h>
#include <IOKit/IOKitLib.h>
#include <OpenGLES/ES2/gl.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "redwood_gl.h"

/* launchd gives a daemon /dev/null for stdio and refuses a job whose
 * StandardOutPath is /dev/console (EACCES); open the console ourselves so the
 * result reaches the kernel log and the persistent recorder. */
static void console_output(void)
{
    int fd = open("/dev/console", O_WRONLY);
    if (fd >= 0) {
        dup2(fd, 1);
        dup2(fd, 2);
        if (fd > 2) { close(fd); }
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}

static void property(CFMutableDictionaryRef props, CFStringRef key, int value)
{
    CFNumberRef number = CFNumberCreate(NULL, kCFNumberIntType, &value);
    CFDictionarySetValue(props, key, number);
    CFRelease(number);
}

static GLuint shader(GLenum kind, const char *text)
{
    GLuint result = glCreateShader(kind);
    glShaderSource(result, 1, &text, NULL);
    glCompileShader(result);
    GLint ok = 0;
    glGetShaderiv(result, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(result, sizeof(log), NULL, log);
        fprintf(stderr, "shader failed: %s\n", log);
        glDeleteShader(result);
        return 0;
    }
    return result;
}

int main(void)
{
    console_output();
    alarm(45);
    printf("citrus-triangle: start\n");
    io_service_t gpu = 0;
    for (unsigned i = 0; i < 300 && !gpu; i++) {
        gpu = IOServiceGetMatchingService(0, IOServiceMatching("RedwoodGPU"));
        if (!gpu) { usleep(100000); }
    }
    if (!gpu) { fprintf(stderr, "FAIL: GPU service absent after 30 seconds\n"); return 1; }
    IOObjectRelease(gpu);
    /* Force the hardware driver: successful softpipe rendering proves nothing. */
    setenv("GALLIUM_DRIVER", "freedreno", 1);
    struct redwood_gl *context = redwood_gl_create(3);
    if (!context || !redwood_gl_make_current(context)) {
        fprintf(stderr, "FAIL: no hardware ES3 context\n");
        return 1;
    }
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("renderer: %s\n", renderer ? renderer : "null");
    if (!renderer || (!strstr(renderer, "FD610") && !(strstr(renderer, "Adreno") && strstr(renderer, "610"))) ||
        strstr(renderer, "softpipe") || strstr(renderer, "llvmpipe")) {
        fprintf(stderr, "FAIL: renderer is not Adreno 610\n");
        return 1;
    }
    CFMutableDictionaryRef props = CFDictionaryCreateMutable(NULL, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    property(props, kIOSurfaceWidth, 64);
    property(props, kIOSurfaceHeight, 64);
    property(props, kIOSurfaceBytesPerElement, 4);
    property(props, kIOSurfaceBytesPerRow, 256);
    property(props, kIOSurfaceAllocSize, 256 * 128); /* guard tile rows */
    property(props, kIOSurfacePixelFormat, 0x42475241); /* BGRA */
    IOSurfaceRef surface = IOSurfaceCreate(props);
    CFRelease(props);
    if (!surface) { fprintf(stderr, "FAIL: IOSurfaceCreate\n"); return 1; }
    GLuint texture = 0, framebuffer = 0;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    if (!redwood_gl_surface_texture(context, IOSurfaceGetID(surface))) {
        fprintf(stderr, "FAIL: IOSurface is not shared with the GPU\n");
        return 1;
    }
    glGenFramebuffers(1, &framebuffer);
    glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FAIL: incomplete framebuffer\n"); return 1;
    }
    GLuint vertex = shader(GL_VERTEX_SHADER, "attribute vec2 p; void main(){gl_Position=vec4(p,0.,1.);}");
    GLuint fragment = shader(GL_FRAGMENT_SHADER, "precision mediump float; void main(){gl_FragColor=vec4(1.,0.,0.,1.);}");
    if (!vertex || !fragment) { return 1; }
    GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glBindAttribLocation(program, 0, "p");
    glLinkProgram(program);
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "FAIL: program link\n"); return 1; }
    glUseProgram(program);
    const GLfloat vertices[] = {-0.8f, -0.8f, 0.8f, -0.8f, 0.f, 0.8f};
    GLuint buffer = 0;
    glGenBuffers(1, &buffer);
    glBindBuffer(GL_ARRAY_BUFFER, buffer);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.f, 0.f, 1.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glFinish();
    unsigned char center[4] = {0}, corner[4] = {0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
    glReadPixels(2, 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
    GLenum error = glGetError();
    int pass = error == GL_NO_ERROR && center[0] > 240 && center[1] < 16 && center[2] < 16 &&
               corner[0] < 16 && corner[1] < 16 && corner[2] > 240;
    /* Read the actual shared surface too, rather than just a GL staging copy.
     * BGRA center must be red; GPU tile layout/readback remains under test. */
    kern_return_t locked = IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL);
    if (locked == KERN_SUCCESS) {
        unsigned char *pixels = IOSurfaceGetBaseAddress(surface);
        size_t offset = 32 * IOSurfaceGetBytesPerRow(surface) + 32 * 4;
        unsigned char *p = pixels ? pixels + offset : NULL;
        pass = pass && p && p[0] < 16 && p[1] < 16 && p[2] > 240;
        if (p) { printf("IOSurface center BGRA: %u,%u,%u,%u\n", p[0], p[1], p[2], p[3]); }
        IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, NULL);
    } else { pass = 0; }
    printf("%s: triangle, GL center=%u,%u,%u corner=%u,%u,%u error=%x\n", pass ? "PASS" : "FAIL",
        center[0], center[1], center[2], corner[0], corner[1], corner[2], error);
    glDeleteBuffers(1, &buffer);
    glDeleteProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    glDeleteFramebuffers(1, &framebuffer);
    glDeleteTextures(1, &texture);
    CFRelease(surface);
    redwood_gl_destroy(context);
    return pass ? 0 : 1;
}
