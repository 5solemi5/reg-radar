"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { Button, Card, Spinner, StateMessage } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/display";

export default function SavedPage() {
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["saved"], queryFn: () => api.listSaved() });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSaved(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved"] }),
  });

  if (saved.isLoading) return <Spinner label="불러오는 중…" />;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">저장함</h1>

      {saved.data?.length === 0 && (
        <StateMessage
          title="저장한 규제가 없습니다"
          description="상세 화면에서 ‘저장함에 담기’를 누르면 여기에 모입니다."
        />
      )}

      <ul className="space-y-3">
        {saved.data?.map((item) => (
          <li key={item.saved_id}>
            <Card className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <Link href={`/results/${item.result_id}`} className="font-medium hover:underline">
                  {item.law_name} {item.article_no}
                </Link>
                {item.note && (
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{item.note}</p>
                )}
                <p className="mt-1 text-xs text-slate-500">{formatDateTime(item.created_at)}</p>
              </div>
              <Button
                variant="ghost"
                onClick={() => remove.mutate(item.saved_id)}
                disabled={remove.isPending}
              >
                삭제
              </Button>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
