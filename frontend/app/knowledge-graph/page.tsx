import { getKnowledgeGraphViewModel } from "@/lib/backend-api";
import { KnowledgeGraphPage } from "@/components/knowledge-graph-page";

export default async function Page() {
  const viewModel = await getKnowledgeGraphViewModel();

  return (
    <KnowledgeGraphPage
      stats={viewModel.stats}
      seeds={viewModel.seedEntities}
      pathItems={viewModel.pathFamilies}
      datasetSections={viewModel.datasetColumns}
      entityDist={viewModel.entityDistribution}
    />
  );
}
