# Architecture — current structural explanation

Stable filenames; the filename stem (uppercased) is the record ID, e.g.
`work-records.md` → `WORK-RECORDS`. Documentation explains structure; it is
never execution authority.

Statuses: `DRAFT CURRENT SUPERSEDED`. `SUPERSEDED` requires `superseded_by`
naming an existing architecture record.

Required front matter: `schema id kind title status owner created updated
related`. Optional: `superseded_by`.
