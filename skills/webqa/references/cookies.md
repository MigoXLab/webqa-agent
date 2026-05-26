# Cookies

Use cookies only when the target page requires login or a specific authenticated state.

## Shape

Pass cookies to `run_test` as an array of objects:

```json
[
  {
    "name": "session",
    "value": "abc123",
    "domain": ".example.com",
    "path": "/",
    "secure": true,
    "httpOnly": true
  }
]
```

Required fields:

- `name`: non-empty cookie name.
- `value`: cookie value; an empty string is allowed if that is the real value.
- Either `domain` or a fully qualified `url` beginning with `http://` or `https://`.

Recommended fields:

- `path`: usually `/`.
- `secure`: `true` for HTTPS cookies.
- `httpOnly`: preserve the browser-exported value when available.

## Collection

Ask the user to export cookie JSON from the browser's developer tools for the target domain. Do not invent authentication cookies.

Before calling `run_test`, check that each cookie has `name`, includes `value`, and has either `domain` or `url`.

## Usage

Use the same `url` domain that the cookies belong to. If cookies are for `.example.com`, the test URL should be under that domain.

If the test still appears logged out, report likely causes:

- Cookie domain does not match the target URL.
- Cookie is expired.
- Required cookies are missing.
- The site also requires local storage, session storage, or multi-factor authentication.
