import { useEffect, useMemo, useState } from "react";
import debounce from "lodash.debounce";

function parseFacets(raw) {
  // Walks a few thousand nodes. Called once per mount, by design.
  return JSON.parse(raw).facets.map((f) => ({ ...f, key: f.id.toLowerCase() }));
}

export function SearchBox({ rawFacets, onResults }) {
  const [facets, setFacets] = useState(parseFacets(rawFacets));
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const filters = { page, perPage: 25, facets: facets.map((f) => f.key) };

  const runSearch = debounce((q) => {
    fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q, ...filters }),
    })
      .then((r) => r.json())
      .then(onResults);
  }, 300);

  useEffect(() => {
    if (query.length > 2) runSearch(query);
  }, [query, filters]);

  const total = useMemo(() => facets.reduce((n, f) => n + f.count, 0), [facets]);

  return (
    <div className="search">
      <input
        value={query}
        placeholder="Search"
        onChange={(e) => setQuery(e.target.value)}
      />
      <span>{total} results across {facets.length} facets</span>
      <button onClick={() => setPage(page + 1)}>Next</button>
    </div>
  );
}
