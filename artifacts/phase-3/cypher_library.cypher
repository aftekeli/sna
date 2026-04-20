// 1-hop: Türkiye Root Films
// Returns all films linked to Turkey (Q43) as country of origin. Root anchor for the entire cinema subgraph.
MATCH (film:Entity)-[:REL {pid: 'P495'}]->(country:Entity {entity_id: 'Q43'})
RETURN film.entity_id AS film_id, film.canonical_name AS film_name, country.canonical_name AS country_name
LIMIT 25;

// 2-hop: Film → Director → Birth Place
// Two-hop path: film directed-by a person, that person born-in a city. Answers "Where was the director of X born?"
MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)
RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place
LIMIT 25;

// 2-hop: Film → Director → Education
// Resolves the school or university each director attended. Covers the most frequent KG-RAG failure mode.
MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P69'}]->(school:Entity)
RETURN film.canonical_name AS film, director.canonical_name AS director, school.canonical_name AS school
LIMIT 25;

// 2-hop: Film → Cast → Birth Place
// Lists cast members alongside their birth cities. Useful for actor-focused place-of-birth questions.
MATCH (film:Entity)-[:REL {pid: 'P161'}]->(actor:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)
RETURN film.canonical_name AS film, actor.canonical_name AS actor, birth_place.canonical_name AS birth_place
LIMIT 25;

// 3-hop: Film → Director → Birth Place → Country
// Full 3-hop chain resolving a director's birth country. Core activation path used by KG-RAG reasoning rounds.
MATCH (film:Entity)-[:REL {pid: 'P57'}]->(director:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)-[:REL {pid: 'P17'}]->(country:Entity)
RETURN film.canonical_name AS film, director.canonical_name AS director, birth_place.canonical_name AS birth_place, country.canonical_name AS country
LIMIT 25;

// 3-hop: Film → Cast → Birth Place → Country
// Mirrors the director path for cast members, resolving birth country across three hops.
MATCH (film:Entity)-[:REL {pid: 'P161'}]->(actor:Entity)-[:REL {pid: 'P19'}]->(birth_place:Entity)-[:REL {pid: 'P17'}]->(country:Entity)
RETURN film.canonical_name AS film, actor.canonical_name AS actor, birth_place.canonical_name AS birth_place, country.canonical_name AS country
LIMIT 25;

// Comparison: Seed Entity Neighbours
// Fetches all direct outgoing relations from a set of seed entities. Used by KG-RAG to rank activation candidates.
MATCH (seed:Entity)-[r:REL]->(neighbour:Entity)
WHERE seed.entity_id IN ['Q6086827', 'Q17560788', 'Q12125563']
RETURN seed.canonical_name AS seed, r.label AS relation, neighbour.canonical_name AS neighbour
ORDER BY seed.entity_id, r.label
LIMIT 30;

// Aggregation: Relation Frequency Summary
// Counts how many times each relation label appears across the full KG. Shows the structural edge-type distribution.
MATCH ()-[r:REL]->()
RETURN r.label AS relation, count(r) AS frequency
ORDER BY frequency DESC
LIMIT 20;
