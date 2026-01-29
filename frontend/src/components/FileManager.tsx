import { Upload, Download, Trash2, File, FileText, Image, FileSpreadsheet, X, Loader2 } from 'lucide-react';
import { useState, useEffect } from 'react';
import { BusinessFile } from '../App';
import { apiClient } from '../api/client';

type Props = {
  businessId: string;
  files: BusinessFile[];
  onFilesChange: (files: BusinessFile[]) => void;
  onClose: () => void;
};

export function FileManager({ businessId, files, onFilesChange, onClose }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load files on mount
  useEffect(() => {
    loadFiles();
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [businessId]);

  const loadFiles = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getFiles(businessId);
      const frontendFiles: BusinessFile[] = response.items.map(f => ({
        id: f.id,
        name: f.name,
        size: f.size,
        type: f.type,
        uploadedAt: f.uploaded_at.split('T')[0],
        url: f.url
      }));
      onFilesChange(frontendFiles);
    } catch (err) {
      console.error('Failed to load files:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (uploadedFiles: FileList | null) => {
    if (!uploadedFiles) return;

    setUploading(true);
    try {
      const uploadPromises = Array.from(uploadedFiles).map(file =>
        apiClient.uploadFile(businessId, file)
      );

      const results = await Promise.all(uploadPromises);

      const newFiles: BusinessFile[] = results.map(f => ({
        id: f.id,
        name: f.name,
        size: f.size,
        type: f.type,
        uploadedAt: f.uploaded_at.split('T')[0],
        url: f.url
      }));

      onFilesChange([...files, ...newFiles]);
    } catch (err) {
      alert('上传失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setUploading(false);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files);
    }
  };

  const handleDelete = async (file: BusinessFile) => {
    if (confirm(`确定要删除文件 "${file.name}" 吗？`)) {
      try {
        await apiClient.deleteFile(businessId, file.name);
        onFilesChange(files.filter(f => f.id !== file.id));
      } catch (err) {
        alert('删除失败: ' + (err instanceof Error ? err.message : '未知错误'));
      }
    }
  };

  const handleDownload = (file: BusinessFile) => {
    // 实际下载逻辑，这里后端应该提供一个静态文件访问路径或下载接口
    // 目前先跳转到 url
    window.open(file.url, '_blank');
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  const getFileIcon = (type: string) => {
    if (type.startsWith('image/')) return <Image className="w-5 h-5 text-blue-500" />;
    if (type.includes('spreadsheet') || type.includes('csv')) return <FileSpreadsheet className="w-5 h-5 text-green-500" />;
    if (type.includes('text')) return <FileText className="w-5 h-5 text-gray-500" />;
    return <File className="w-5 h-5 text-gray-400" />;
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center p-0 sm:p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
      <div className="bg-white w-full h-full sm:h-auto sm:rounded-lg sm:max-w-4xl overflow-hidden flex flex-col max-h-screen sm:max-h-[90vh]">
        <div className="p-4 sm:p-6 border-b border-gray-200 flex items-center justify-between sticky top-0 bg-white z-10">
          <h2>文件管理</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
          {/* Upload Area */}
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
              dragActive
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-300 hover:border-gray-400'
            } ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {uploading ? (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="w-12 h-12 text-blue-600 animate-spin" />
                <p className="text-gray-600">正在上传...</p>
              </div>
            ) : (
              <>
                <p className="text-gray-600 mb-2">拖拽文件到此处，或点击上传</p>
                <p className="text-sm text-gray-500 mb-4">支持所有文件类型</p>
                <label className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors cursor-pointer">
                  <Upload className="w-5 h-5" />
                  选择文件
                  <input
                    type="file"
                    multiple
                    onChange={(e) => handleFileUpload(e.target.files)}
                    className="hidden"
                    disabled={uploading}
                  />
                </label>
              </>
            )}
          </div>

          {/* File List */}
          <div>
            <h3 className="mb-4">已上传文件 ({files.length})</h3>

            {files.length === 0 ? (
              <div className="text-center py-12 border border-gray-200 rounded-lg bg-gray-50">
                <File className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">还没有上传任何文件</p>
              </div>
            ) : (
              <div className="space-y-2">
                {files.map((file) => (
                  <div
                    key={file.id}
                    className="flex items-center gap-3 p-3 sm:p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex-shrink-0">
                      {getFileIcon(file.type)}
                    </div>

                    <div className="flex-1 min-w-0">
                      <p className="text-sm sm:text-base truncate">{file.name}</p>
                      <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-xs sm:text-sm text-gray-500 mt-1">
                        <span>{formatFileSize(file.size)}</span>
                        <span>·</span>
                        <span>{file.uploadedAt}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 sm:gap-2 flex-shrink-0">
                      <button
                        onClick={() => handleDownload(file)}
                        className="p-2 hover:bg-blue-50 text-blue-600 rounded-lg transition-colors"
                        title="下载"
                      >
                        <Download className="w-4 h-4 sm:w-5 sm:h-5" />
                      </button>
                      <button
                        onClick={() => handleDelete(file)}
                        className="p-2 hover:bg-red-50 text-red-600 rounded-lg transition-colors"
                        title="删除"
                      >
                        <Trash2 className="w-4 h-4 sm:w-5 sm:h-5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-4 sm:p-6 border-t border-gray-200 flex justify-end sticky bottom-0 bg-white">
          <button
            onClick={onClose}
            className="w-full sm:w-auto px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  );
}
