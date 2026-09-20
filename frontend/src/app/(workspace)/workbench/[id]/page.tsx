import WorkbenchView from "./workbench-view";

export default async function WorkbenchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return <WorkbenchView key={id} documentId={id} />;
}
