import { getCypherViewModel } from "@/lib/backend-api";
import { CypherQueriesPage } from "@/components/cypher-queries-page";

export default async function Page() {
  const viewModel = await getCypherViewModel();

  return (
    <CypherQueriesPage
      stats={viewModel.stats}
      queries={viewModel.queryLibrary as Parameters<typeof CypherQueriesPage>[0]["queries"]}
    />
  );
}
