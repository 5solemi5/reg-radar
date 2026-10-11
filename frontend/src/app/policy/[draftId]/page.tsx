import { PolicyDraftDetail } from "@/components/policy/draft-detail";

/** Next 16부터 params는 async다. */
export default async function PolicyDraftPage(props: PageProps<"/policy/[draftId]">) {
  const { draftId } = await props.params;
  return <PolicyDraftDetail draftId={draftId} />;
}
