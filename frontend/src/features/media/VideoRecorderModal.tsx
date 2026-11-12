import React from "react";
import { Modal } from "../../components/Modal";
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
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Record Your Video Résumé"
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
