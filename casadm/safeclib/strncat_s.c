/*------------------------------------------------------------------
  * strncat_s.c
  *
  * October 2008, Bo Berry
  *
  * Copyright (c) 2008-2011 by Cisco Systems, Inc
  * All rights reserved.
  *
  * Permission is hereby granted, free of charge, to any person
  * obtaining a copy of this software and associated documentation
  * files (the "Software"), to deal in the Software without
  * restriction, including without limitation the rights to use,
  * copy, modify, merge, publish, distribute, sublicense, and/or
  * sell copies of the Software, and to permit persons to whom the
  * Software is furnished to do so, subject to the following
  * conditions:
  *
  * The above copyright notice and this permission notice shall be
  * included in all copies or substantial portions of the Software.
  *
  * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
  * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
  * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
  * NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
  * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
  * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
  * OTHER DEALINGS IN THE SOFTWARE.
  *------------------------------------------------------------------
  */

 #include "safeclib_private.h"
 #include "safe_str_constraint.h"
 #include "safe_str_lib.h"


 errno_t
 strncat_s (char * restrict dest, rsize_t dmax, const char * restrict src, rsize_t slen)
 {
     rsize_t orig_dmax;
     char *orig_dest;
     const char *overlap_bumper;

     if (dest == NULL) {
         invoke_safe_str_constraint_handler("strncat_s: dest is null",
                    NULL, ESNULLP);
         return RCNEGATE(ESNULLP);
     }

     if (src == NULL) {
         invoke_safe_str_constraint_handler("strncat_s: src is null",
                    NULL, ESNULLP);
         return RCNEGATE(ESNULLP);
     }

     if (slen > RSIZE_MAX_STR) {
         invoke_safe_str_constraint_handler("strncat_s: slen exceeds max",
                    NULL, ESLEMAX);
         return RCNEGATE(ESLEMAX);
     }

     if (dmax == 0) {
         invoke_safe_str_constraint_handler("strncat_s: dmax is 0",
                    NULL, ESZEROL);
         return RCNEGATE(ESZEROL);
     }

     if (dmax > RSIZE_MAX_STR) {
         invoke_safe_str_constraint_handler("strncat_s: dmax exceeds max",
                    NULL, ESLEMAX);
         return RCNEGATE(ESLEMAX);
     }

     /* hold base of dest in case src was not copied */
     orig_dmax = dmax;
     orig_dest = dest;

     if (dest < src) {
         overlap_bumper = src;

         /* Find the end of dest */
         while (*dest != '\0') {

             if (dest == overlap_bumper) {
                 handle_error(orig_dest, orig_dmax, "strncat_s: "
                         "overlapping objects",
                         ESOVRLP);
                 return RCNEGATE(ESOVRLP);
             }

             dest++;
             dmax--;
             if (dmax == 0) {
                 handle_error(orig_dest, orig_dmax, "strncat_s: "
                        "dest unterminated",
                        ESUNTERM);
                 return RCNEGATE(ESUNTERM);
             }
         }

         while (dmax > 0) {
             if (dest == overlap_bumper) {
                 handle_error(orig_dest, orig_dmax, "strncat_s: "
                        "overlapping objects",
                        ESOVRLP);
                 return RCNEGATE(ESOVRLP);
             }

             /*
              * Copying truncated before the source null is encountered
              */
             if (slen == 0) {
 #ifdef SAFECLIB_STR_NULL_SLACK
                 /* null remaining string */
                 while (dmax) { *dest = '\0'; dmax--; dest++; }
 #else
                 *dest = '\0';
 #endif
                 return RCNEGATE(EOK);
             }

             *dest = *src;
             if (*dest == '\0') {
 #ifdef SAFECLIB_STR_NULL_SLACK
                 /* null slack to clear data */
                 while (dmax) { *dest = '\0'; dmax--; dest++; }
 #endif
                 return RCNEGATE(EOK);
             }

             dmax--;
             slen--;
             dest++;
             src++;
         }

     } else {
         overlap_bumper = dest;

         /* Find the end of dest */
         while (*dest != '\0') {

             /*
              * NOTE: no need to check for overlap here since src comes first
              * in memory and we're not incrementing src here.
              */
             dest++;
             dmax--;
             if (dmax == 0) {
                 handle_error(orig_dest, orig_dmax, "strncat_s: "
                        "dest unterminated",
                        ESUNTERM);
                 return RCNEGATE(ESUNTERM);
             }
         }

         while (dmax > 0) {
             if (src == overlap_bumper) {
                 handle_error(orig_dest, orig_dmax, "strncat_s: "
                         "overlapping objects",
                         ESOVRLP);
                 return RCNEGATE(ESOVRLP);
             }

             /*
              * Copying truncated
              */
             if (slen == 0) {
 #ifdef SAFECLIB_STR_NULL_SLACK
                 /* null remaining string */
                 while (dmax) { *dest = '\0'; dmax--; dest++; }
 #else
                 *dest = '\0';
 #endif
                 return RCNEGATE(EOK);
             }

             *dest = *src;
             if (*dest == '\0') {
 #ifdef SAFECLIB_STR_NULL_SLACK
                 /* null slack to clear any data */
                 while (dmax) { *dest = '\0'; dmax--; dest++; }
 #endif
                 return RCNEGATE(EOK);
             }

             dmax--;
             slen--;
             dest++;
             src++;
         }
     }

     /*
      * the entire src was not copied, so the string will be nulled.
      */
     handle_error(orig_dest, orig_dmax, "strncat_s: not enough "
                  "space for src",
                  ESNOSPC);
     return RCNEGATE(ESNOSPC);
 }
 EXPORT_SYMBOL(strncat_s)
