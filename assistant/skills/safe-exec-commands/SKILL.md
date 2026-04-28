---
name: safe-exec-commands
description: Use when the Discord bot agent needs to explain or use its safe utility commands for date/time lookup, mathematical calculations, or random number generation through safe_exec.
---

# Safe Exec Commands

Use `safe_exec` in agent mode when a user asks for date/time, timezone conversion, a calculation, or a random number.

For those requests, always call `safe_exec` before answering. Do not answer from memory, mental math, model knowledge, or inferred current time.

## Command Forms

Use the `command` field with one of these forms:

```text
date
time
datetime
timezone
timezone AREA/LOCATION
math EXPRESSION
random
random MIN MAX
```

## Time Commands

Use `date` for the local date:

```text
date
```

Use `time` for the local time with timezone:

```text
time
```

Use `datetime` for the full local datetime:

```text
datetime
```

Use `timezone` for the local timezone:

```text
timezone
```

Use `timezone AREA/LOCATION` for the current datetime in an IANA timezone:

```text
timezone Asia/Taipei
timezone America/New_York
timezone Europe/London
```

## Math Commands

Use `math EXPRESSION` for calculations:

```text
math 2^3 + 4
math sqrt(16) + sin(pi / 2)
math log(100, 10) + factorial(5)
math comb(10, 3) + perm(5, 2)
math hypot(3, 4) + degrees(pi)
math exp(2) + ln(e)
```

Supported operators:

```text
+ - * / // % ** ^
```

Supported constants:

```text
pi e tau
```

Supported functions:

```text
abs round min max sqrt cbrt
sin cos tan asin acos atan atan2
sinh cosh tanh degrees radians
log log10 log2 ln exp pow
floor ceil trunc factorial comb perm
gcd lcm hypot
```

## Random Commands

Use `random` for a decimal number in `[0, 1)`:

```text
random
```

Use `random MIN MAX` for an integer in an inclusive range:

```text
random 1 100
random -10 10
```

## Tool Call Examples

```json
{"command": "datetime"}
```

```json
{"command": "timezone Asia/Taipei"}
```

```json
{"command": "math sqrt(16) + sin(pi / 2)"}
```

```json
{"command": "random 1 100"}
```
