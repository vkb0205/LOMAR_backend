# Catalog contracts

Catalog endpoints are public and return only active vendors and services.

- `GET /api/v1/catalog/vendors` returns `{ "vendors": [...] }`.
- `GET /api/v1/catalog/vendors/{vendorId}` returns the vendor and its services.
- `GET /api/v1/catalog/customize` returns
  `{ "services": [...], "vendors": [...] }`.
- `GET /api/v1/catalog/services/{serviceId}/suggestion` returns one visible
  service or `404`.

Services expose their display image through `services.thumbnail_url`.
`service_images` is no longer part of the schema or response contract.
Database availability failures use the sanitized `503 database_unavailable`
response.
