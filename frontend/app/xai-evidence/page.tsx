import { getXaiViewModel } from "@/lib/backend-api";
import { XaiEvidencePage } from "@/components/xai-evidence-page";

export default async function Page() {
  const viewModel = await getXaiViewModel();

  return <XaiEvidencePage stats={viewModel.stats} success={viewModel.successCase} failures={viewModel.failures} />;
}
