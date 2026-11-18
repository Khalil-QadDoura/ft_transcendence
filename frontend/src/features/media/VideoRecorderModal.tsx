import React from "react";
import { Modal } from "../../components/Modal";
import { useText } from "../../i18n/useText";
import { VideoRecorder } from "./VideoRecorder";
import type { VideoStatusOut } from "./types";

export interface VideoRecorderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadSuccess?: (result: VideoStatusOut) => void;
  maxDurationSec?: number;
}

export const VideoRecorderModal: React.FC<VideoRecorderModalProps> = ({
  isOpen,
  onClose,
  onUploadSuccess,
  maxDurationSec,
}) => {
  const { t } = useText();
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t("media.modalTitle")}
      size="lg"
    >
      <div className="p-2">
        <VideoRecorder
          maxDurationSec={maxDurationSec}
          onCancel={onClose}
          onUploadSuccess={(result) => {
            if (onUploadSuccess) {
              onUploadSuccess(result);
            }
            setTimeout(() => {
              onClose();
            }, 1200);
          }}
        />
      </div>
    </Modal>
  );
};
