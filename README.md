# arianet-python

The official Python client for the [Arianet](https://ariaservice.net) public API: Cloud, classic
and regional VPS, hosting, dedicated servers (bare metal), SMS, and your account (API tokens, SSH
keys, firewalls, balance, invoices).

- One method per API operation, generated from the published OpenAPI specs.
- Personal API token auth, retries on `429` that honor `Retry-After`, safe retries of reads and
  idempotent writes after network errors and `502`/`503`/`504`.
- Typed exceptions carrying the API's stable error codes.
- No dependencies outside the standard library. Python 3.10 or newer.

Documentation: <https://docs.ariaservice.net/sdk/python>

## Install

```bash
pip install arianet
```

Until the package is on PyPI, install a release straight from GitHub:

```bash
pip install "git+https://github.com/ariaservice/arianet-python@v0.1.0"
```

## Quickstart

Create a personal API token at <https://cloud.ariaservice.net/users/api-tokens> and export it:

```bash
export ARIANET_TOKEN="paste-your-token-here"
```

```python
import arianet

client = arianet.Client()  # reads ARIANET_TOKEN

page = client.cloud.list_servers(per_page=50, label_selector="env=prod")
for server in page["data"]:
    print(server["id"], server["name"], server["status"])
```

## API groups

| Attribute             | API                                                               | Path prefix     |
|-----------------------|-------------------------------------------------------------------|-----------------|
| `client.core`         | Account, API tokens, classic VPS, SSH keys, firewalls, billing    | `/api/v1`       |
| `client.cloud`        | Cloud servers, volumes, networks, firewalls, IPs, load balancers  | `/cloud/v1`     |
| `client.regional_vps` | Regional VPS                                                      | `/vps/v1`       |
| `client.hosting`      | Hosting accounts, DNS, mailboxes, databases                       | `/hosting/v1`   |
| `client.baremetal`    | Dedicated servers                                                 | `/baremetal/v1` |
| `client.sms`          | SMS messages, templates, lines, webhooks                          | `/sms/v1`       |

Method names are the snake_case `operationId` of each operation in the API reference
(<https://docs.ariaservice.net/api-reference>): `listServers` becomes `list_servers`. Path
parameters are positional, the JSON request body is the `body` argument (a dict or list), and
query parameters are keyword arguments (a parameter named like a Python keyword gets a trailing
underscore, e.g. `from_`). Every method returns the decoded JSON response.

```python
server = client.cloud.create_server({
    "name": "web-1",
    "plan_id": 101,            # from client.cloud.list_plans()
    "image": "ubuntu-24.04",   # an image slug from client.cloud.list_images()
    "datacenter": "ovh",       # a datacenter code from client.cloud.list_datacenters()
})
```

## Configuration

```python
client = arianet.Client(
    "token",                                  # default: ARIANET_TOKEN
    base_url="https://api.ariaservice.net",   # default, or ARIANET_API_URL
    timeout=60.0,                             # seconds per HTTP attempt
    max_retries=3,
    max_retry_wait=60.0,                      # longest wait before one retry
    user_agent="my-app/1.2",
)
```

The base URL must use `https` (plain `http` is accepted for `localhost` only). The client never
follows redirects, so the token is only ever sent to the API host.

## Retries and rate limits

- `429 Too Many Requests` is retried for every method, after the `Retry-After` header (or
  `RateLimit-Reset`). If the server asks for a longer wait than `max_retry_wait`,
  `arianet.RateLimitError` is raised at once with `retry_after` set.
- Network errors and `502`/`503`/`504` are retried only when repeating cannot do the work twice:
  `GET`/`HEAD` requests and requests with an `Idempotency-Key`.
- Operations that accept an `Idempotency-Key` (creating a server, an order, a hosting account...)
  get a generated key automatically, so they are retried safely. Pass `idempotency_key="..."` to
  make retries across process restarts safe too.

## Errors

```python
from arianet import ErrorCode

try:
    client.core.create_server(order)
except arianet.APIError as err:
    if err.code == ErrorCode.INSUFFICIENT_BALANCE:
        ...  # top up the wallet
    else:
        print(err.status_code, err.code, err.message, err.request_id)
except arianet.APIConnectionError:
    ...  # no answer: DNS, TLS, timeout
```

`err.code` is the API's stable machine code, always lower-cased (the core API's
`INSUFFICIENT_BALANCE` becomes `insufficient_balance`), so it can be compared with the generated
`ErrorCode` constants. Branch on the code, not on `message`. `err.reason` narrows the code on some
refusals (for example `identity_hold`).

Exception classes by status: `BadRequestError` (400), `AuthenticationError` (401),
`PaymentRequiredError` (402), `PermissionDeniedError` (403), `NotFoundError` (404),
`ConflictError` (409), `UnprocessableEntityError` (422), `RateLimitError` (429),
`InternalServerError` (5xx); all subclass `APIError`, which subclasses `ArianetError`.

## Regions

Product APIs with regional installs take the `Arianet-Region` header:

```python
iran = client.regional_vps.with_region("iran-1")
servers = iran.list_servers()
```

## Endpoints not in this version

`client.request(method, path, query=..., body=...)` calls any path with the same auth, retries and
error handling:

```python
client.request("GET", "/cloud/v1/new-endpoint", query={"page": 2})
```

## How the code is generated

`specs/` holds the published OpenAPI documents and `codegen/services.json` lists where they come
from. `src/arianet/_services.py`, `_error_codes.py` and `_wiring.py` are produced by
`codegen/generate.py` (standard library only):

```bash
python3 codegen/fetch_specs.py   # refresh specs/ (needs: pip install pyyaml)
python3 codegen/generate.py
python3 codegen/generate.py --check
```

The *Regenerate from specs* workflow does this every day and opens a pull request when the
published specs change. The rest of `src/arianet/` is hand-written and never touched by the
generator.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## License

MIT, see [LICENSE](LICENSE). Report security problems privately, see [SECURITY.md](SECURITY.md).
