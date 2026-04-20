import { getEvaluationViewModel } from "@/lib/backend-api";
import { GnnPage } from "@/components/gnn-page";

export default async function Page() {
  const viewModel = await getEvaluationViewModel();

  return <GnnPage stats={viewModel.stats} methods={viewModel.methodMetrics} bars={viewModel.domainBars} hopTypes={viewModel.hopTypeMetrics} questionGrid={viewModel.questionGrid} />;
}
