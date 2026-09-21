import { ResultDetail } from "@/components/result-detail";

/** Next 16부터 params는 async다. */
export default async function ResultPage(props: PageProps<"/results/[resultId]">) {
  const { resultId } = await props.params;
  return <ResultDetail resultId={resultId} />;
}
