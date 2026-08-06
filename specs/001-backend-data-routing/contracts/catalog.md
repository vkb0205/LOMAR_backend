# Catalog contracts (US1, P1)

Replaces: `vendorCatalogService.ts`, `vendorDetailService.ts`,
`customizeCatalogService.ts`, `serviceSuggestionService.ts`.

All endpoints in this slice are **public** (no session required), matching
FR-006. All return `503 database_unavailable` on DB failure so the frontend
can show the "unavailable" state (SC-005).

## `GET /api/v1/catalog/vendors`

Returns the vendor card list.

**Response 200**
```json
{
  "vendors": [
    {
      "id": "uuid",
      "name": "string",
      "category": "string",
      "status": "active",
      "...": "all VendorCardModel fields fetchVendorCatalog() produced"
    }
  ]
}
```

## `GET /api/v1/catalog/vendors/{vendorId}`

Returns one vendor's profile and its services, matching
`VendorDetailPage`'s current query shape.

**Response 200**
```json
{
  "vendor": { "...": "VendorDetailVendor fields" },
  "services": [{ "...": "VendorDetailService fields" }]
}
```

**Response 404** — vendor not found: `{ "error": { "code": "not_found" } }`

## `GET /api/v1/catalog/customize`

Returns the combined services + service_images + vendors payload consumed by
the customization flow.

**Response 200**
```json
{
  "services": [{ "...": "ServiceRow" }],
  "serviceImages": [{ "...": "ServiceImageRow" }],
  "vendors": [{ "...": "VendorRow" }]
}
```

## `GET /api/v1/catalog/services/{serviceId}/suggestion`

Replaces `serviceSuggestionService.ts`'s lookup used by the AI consultant to
attach a suggested-service card to a chat message.

**Response 200**: `{ "service": { "...": "ServiceRow" } }`
**Response 404**: unknown or non-catalog-visible service ID.
