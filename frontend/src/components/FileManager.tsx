import { Upload, Download, Trash2, File, FileText, Image, FileSpreadsheet, Loader2 } from 'lucide-react';
import { useState, useEffect } from 'react';
import { BusinessFile } from '../App';
import { apiClient } from '../api/client';

type Props = {
  businessId: string;
  files: BusinessFile[];
  onFilesChange: (files: BusinessFile[]) => void;
  onClose?: () => void;
  inline?: boolean;
};

export function FileManager({ businessId, files, onFilesChange, onClose, inline = false }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load files on mount
  useEffect(() => {
    loadFiles();
    if (!inline) {
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = '';
      };
    }
  }, [businessId, inline]);

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

  const renderContent = () => (
    <div className={inline ? 'space-y-4' : 'flex-1 overflow-y-auto space-y-6'} style={inline ? undefined : { padding: '24px 28px' }}>
      {/* Upload Area */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
          dragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400'
        } ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        {uploading ? (
          <div className="flex items-center justify-center gap-2">
            <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />
            <p className="text-sm text-gray-600">正在上传...</p>
          </div>
        ) : (
          <div className="flex items-center justify-center gap-3">
            <p className="text-sm text-gray-500">拖拽文件到此处，或</p>
            <label className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors cursor-pointer text-sm">
              <Upload className="w-4 h-4" />
              选择文件
              <input
                type="file"
                multiple
                onChange={(e) => handleFileUpload(e.target.files)}
                className="hidden"
                disabled={uploading}
              />
            </label>
          </div>
        )}
      </div>

      {/* File List */}
      <div>
        <h3 className="mb-4 text-sm text-gray-700">已上传文件 ({files.length})</h3>

        {files.length === 0 ? (
          <div className="text-center py-8 border border-gray-200 rounded-lg bg-gray-50">
            <File className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">还没有上传任何文件</p>
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
                    className="p-1.5 hover:bg-blue-50 text-blue-600 rounded-lg transition-colors"
                    title="下载"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(file)}
                    className="p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4 text-red-600" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // Inline mode: render content directly without modal wrapper
  if (inline) {
    return renderContent();
  }

  // Modal mode: render with overlay
  return (
    <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
      <div className="bg-white rounded-lg flex flex-col shadow-2xl" style={{ width: '960px', maxWidth: '90vw', maxHeight: 'calc(100vh - 64px)' }}>
        <div className="border border-gray-200 rounded-lg flex flex-col flex-1 min-h-0 overflow-hidden">
          {/* Header */}
          <div className="border-b border-gray-200 flex-shrink-0" style={{ padding: '16px 28px' }}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">文件管理</h2>
              <button
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
              >
                关闭
              </button>
            </div>
          </div>

          {/* Content */}
          {renderContent()}
        </div>
      </div>
    </div>
  );
}
