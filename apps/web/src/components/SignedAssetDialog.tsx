"use client";

import { useEffect } from "react";
import Image from "next/image";
import { X } from "lucide-react";
import type { TranslationCatalog } from "@chair/shared-types";

interface SignedAssetDialogProps {
  t: TranslationCatalog;
  asset: { blobUrl: string; mimeType: string } | null;
  onClose: () => void;
}

export function SignedAssetDialog({ t, asset, onClose }: SignedAssetDialogProps) {
  useEffect(() => {
    if (!asset) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [asset, onClose]);

  if (!asset) {
    return null;
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t.partner.previewTitle}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-2xl rounded-lg border border-[#E2DACD] bg-[#FAF7F2] p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-semibold text-[#1C1B19]">{asset.mimeType}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.partner.closePreviewBtn}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded border border-[#E2DACD] bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {asset.mimeType.startsWith("image/") ? (
          <Image
            src={asset.blobUrl}
            alt={t.partner.previewTitle}
            width={800}
            height={600}
            unoptimized
            className="max-h-[70vh] w-full rounded object-contain"
          />
        ) : (
          <iframe
            src={asset.blobUrl}
            title={t.partner.previewTitle}
            className="h-[70vh] w-full rounded border border-[#E2DACD]"
          />
        )}
      </div>
    </div>
  );
}
