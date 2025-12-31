/*
 * Coex Regex FFI Wrapper
 *
 * Wraps Henry Spencer's BSD regex library (rxspencer) for use from Coex.
 * Provides a handle-based API that manages regex_t structures internally.
 *
 * Functions:
 *   coex_regex_compile    - Compile a pattern, return handle
 *   coex_regex_match      - Test if pattern matches string
 *   coex_regex_match_pos  - Get match positions
 *   coex_regex_free       - Free a compiled regex
 *   coex_regex_error      - Get error message for error code
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "rxspencer/regex.h"

/* Debug flag - set to 1 to enable tracing */
#define DEBUG_REGEX 0

#if DEBUG_REGEX
#define DEBUG_PRINT(...) fprintf(stderr, __VA_ARGS__)
#else
#define DEBUG_PRINT(...) ((void)0)
#endif

/* Maximum number of compiled regex handles */
#define MAX_REGEX_HANDLES 1024

/* Handle table for compiled regex objects */
static regex_t* regex_handles[MAX_REGEX_HANDLES];
static int handle_in_use[MAX_REGEX_HANDLES];

/*
 * Compile a regex pattern.
 *
 * @param pattern  The regex pattern string (null-terminated)
 * @param flags    Compilation flags (REG_EXTENDED, REG_ICASE, etc.)
 * @return Handle (> 0) on success, negative error code on failure
 *
 * Error codes:
 *   -1: No free handle slots
 *   -2: Memory allocation failed
 *   -100 - errcode: Regex compilation error (add 100 to get actual error)
 */
int64_t coex_regex_compile(const char* pattern, int32_t flags) {
    DEBUG_PRINT("[REGEX] compile called: pattern='%s', flags=%d\n", pattern ? pattern : "(null)", flags);
    if (!pattern) return -3;

    /* Find free slot */
    int slot = -1;
    for (int i = 0; i < MAX_REGEX_HANDLES; i++) {
        if (!handle_in_use[i]) {
            slot = i;
            break;
        }
    }
    DEBUG_PRINT("[REGEX] compile: found free slot=%d\n", slot);
    if (slot < 0) return -1;  /* No free slots */

    /* Allocate regex_t */
    regex_t* preg = (regex_t*)malloc(sizeof(regex_t));
    if (!preg) return -2;  /* Allocation failed */

    /* Compile pattern */
    int result = regcomp(preg, pattern, flags);
    DEBUG_PRINT("[REGEX] compile: regcomp result=%d, preg=%p\n", result, (void*)preg);
    if (result != 0) {
        free(preg);
        return -(100 + result);  /* Return negative error code */
    }

    /* Store in slot - handle is slot + 1 (so handles start at 1, not 0) */
    regex_handles[slot] = preg;
    handle_in_use[slot] = 1;

    DEBUG_PRINT("[REGEX] compile: SUCCESS handle=%d, slot=%d, preg=%p\n", slot + 1, slot, (void*)preg);
    return (int64_t)(slot + 1);
}

/*
 * Test if a pattern matches a string.
 *
 * @param handle  Handle from coex_regex_compile
 * @param text    String to match against (null-terminated)
 * @param eflags  Execution flags (REG_NOTBOL, REG_NOTEOL)
 * @return 0 = match, 1 = no match, negative = error
 */
int64_t coex_regex_match(int64_t handle, const char* text, int32_t eflags) {
    DEBUG_PRINT("[REGEX] match called: handle=%lld, text='%s', eflags=%d\n", (long long)handle, text ? text : "(null)", eflags);
    if (handle <= 0 || handle > MAX_REGEX_HANDLES) {
        DEBUG_PRINT("[REGEX] match: INVALID handle (out of range)\n");
        return -1;
    }
    if (!text) return -2;

    int slot = (int)(handle - 1);
    DEBUG_PRINT("[REGEX] match: slot=%d, handle_in_use=%d\n", slot, handle_in_use[slot]);
    if (!handle_in_use[slot]) {
        DEBUG_PRINT("[REGEX] match: SLOT NOT IN USE\n");
        return -3;
    }

    regex_t* preg = regex_handles[slot];
    DEBUG_PRINT("[REGEX] match: preg=%p\n", (void*)preg);
    if (!preg) return -4;

    int result = regexec(preg, text, 0, NULL, eflags);
    DEBUG_PRINT("[REGEX] match: regexec result=%d (0=match, non-zero=no match)\n", result);
    return (result == 0) ? 0 : 1;
}

/*
 * Match a pattern and get the position of the match.
 *
 * @param handle     Handle from coex_regex_compile
 * @param text       String to match against
 * @param eflags     Execution flags
 * @param start_out  Output: start position of match (-1 if no match)
 * @param end_out    Output: end position of match (-1 if no match)
 * @return 0 = match found, 1 = no match, negative = error
 */
int64_t coex_regex_match_pos(int64_t handle, const char* text, int32_t eflags,
                              int64_t* start_out, int64_t* end_out) {
    if (handle <= 0 || handle > MAX_REGEX_HANDLES) return -1;
    if (!text || !start_out || !end_out) return -2;

    int slot = (int)(handle - 1);
    if (!handle_in_use[slot]) return -3;

    regex_t* preg = regex_handles[slot];
    if (!preg) return -4;

    regmatch_t pmatch[1];
    int result = regexec(preg, text, 1, pmatch, eflags);

    if (result == 0) {
        *start_out = pmatch[0].rm_so;
        *end_out = pmatch[0].rm_eo;
        return 0;
    } else {
        *start_out = -1;
        *end_out = -1;
        return 1;
    }
}

/*
 * Match with capture groups.
 *
 * @param handle      Handle from coex_regex_compile
 * @param text        String to match against
 * @param eflags      Execution flags
 * @param max_groups  Maximum number of groups to capture
 * @param buffer      Output buffer for match positions (pairs of i64: start, end)
 * @param buf_size    Size of buffer in bytes
 * @return Number of groups captured (0 if no match), negative on error
 */
int64_t coex_regex_match_groups(int64_t handle, const char* text, int32_t eflags,
                                 int32_t max_groups, int64_t* buffer, int64_t buf_size) {
    if (handle <= 0 || handle > MAX_REGEX_HANDLES) return -1;
    if (!text || !buffer) return -2;
    if (max_groups <= 0) return -3;
    if (buf_size < max_groups * 2 * (int64_t)sizeof(int64_t)) return -4;

    int slot = (int)(handle - 1);
    if (!handle_in_use[slot]) return -5;

    regex_t* preg = regex_handles[slot];
    if (!preg) return -6;

    regmatch_t* pmatch = (regmatch_t*)malloc(max_groups * sizeof(regmatch_t));
    if (!pmatch) return -7;

    int result = regexec(preg, text, max_groups, pmatch, eflags);

    if (result != 0) {
        free(pmatch);
        return 0;  /* No match */
    }

    /* Copy match positions to buffer */
    int count = 0;
    for (int i = 0; i < max_groups && pmatch[i].rm_so != -1; i++) {
        buffer[i * 2] = pmatch[i].rm_so;
        buffer[i * 2 + 1] = pmatch[i].rm_eo;
        count++;
    }

    free(pmatch);
    return count;
}

/*
 * Free a compiled regex.
 *
 * @param handle  Handle from coex_regex_compile
 * @return 0 on success, negative on error
 */
int64_t coex_regex_free(int64_t handle) {
    DEBUG_PRINT("[REGEX] free called: handle=%lld\n", (long long)handle);
    if (handle <= 0 || handle > MAX_REGEX_HANDLES) return -1;

    int slot = (int)(handle - 1);
    DEBUG_PRINT("[REGEX] free: slot=%d, handle_in_use=%d\n", slot, handle_in_use[slot]);
    if (!handle_in_use[slot]) return -2;

    regex_t* preg = regex_handles[slot];
    DEBUG_PRINT("[REGEX] free: preg=%p\n", (void*)preg);
    if (preg) {
        regfree(preg);
        free(preg);
    }

    regex_handles[slot] = NULL;
    handle_in_use[slot] = 0;

    DEBUG_PRINT("[REGEX] free: SUCCESS slot=%d now free\n", slot);
    return 0;
}

/*
 * Get error message for a compilation error code.
 *
 * @param error_code  Error code from coex_regex_compile (negative value)
 * @param buffer      Buffer to write error message
 * @param buf_size    Size of buffer
 * @return Length of error message, or negative on error
 */
int64_t coex_regex_error(int64_t error_code, char* buffer, int64_t buf_size) {
    if (!buffer || buf_size <= 0) return -1;

    /* Handle special error codes */
    if (error_code == -1) {
        strncpy(buffer, "No free regex handle slots", buf_size - 1);
        buffer[buf_size - 1] = '\0';
        return strlen(buffer);
    }
    if (error_code == -2) {
        strncpy(buffer, "Memory allocation failed", buf_size - 1);
        buffer[buf_size - 1] = '\0';
        return strlen(buffer);
    }
    if (error_code == -3) {
        strncpy(buffer, "NULL pattern", buf_size - 1);
        buffer[buf_size - 1] = '\0';
        return strlen(buffer);
    }

    /* Convert error code back to regerror code */
    int regerr = (int)(-(error_code + 100));
    if (regerr < 0) {
        strncpy(buffer, "Unknown error", buf_size - 1);
        buffer[buf_size - 1] = '\0';
        return strlen(buffer);
    }

    /* Use regerror - needs a regex_t but only uses it for locale */
    regex_t dummy;
    memset(&dummy, 0, sizeof(dummy));
    size_t len = regerror(regerr, &dummy, buffer, buf_size);

    return (int64_t)len;
}
