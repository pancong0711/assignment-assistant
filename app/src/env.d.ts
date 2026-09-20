/// <reference types="vite/client" />

// File System Access API（Chrome/Edge 支持，Firefox/Safari 缺失 → D11 降级）
interface FileSystemShowDirectoryPickerOptions {
  mode?: 'read' | 'readwrite'
  id?: string
  startIn?: string
}
interface FileSystemShowOpenFilePickerOptions {
  multiple?: boolean
  types?: Array<{
    description?: string
    accept: Record<string, string[]>
  }>
}
interface FileSystemShowSaveFilePickerOptions {
  suggestedName?: string
  types?: Array<{
    description?: string
    accept: Record<string, string[]>
  }>
  startIn?: string
}

interface Window {
  showDirectoryPicker?: (options?: FileSystemShowDirectoryPickerOptions) => Promise<FileSystemDirectoryHandle>
  showOpenFilePicker?: (options?: FileSystemShowOpenFilePickerOptions) => Promise<FileSystemFileHandle[]>
  showSaveFilePicker?: (options?: FileSystemShowSaveFilePickerOptions) => Promise<FileSystemFileHandle>
}

interface FileSystemHandle {
  readonly kind: 'file' | 'directory'
  readonly name: string
}

interface FileSystemFileHandle {
  readonly kind: 'file'
  readonly name: string
  createWritable?: (options?: { keepExistingData?: boolean }) => Promise<FileSystemWritableFileStream>
  getFile: () => Promise<File>
}
interface FileSystemDirectoryHandle {
  readonly kind: 'directory'
  readonly name: string
  queryPermission?: (descriptor: { mode: 'read' | 'readwrite' }) => Promise<PermissionState>
  requestPermission?: (descriptor: { mode: 'read' | 'readwrite' }) => Promise<PermissionState>
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<FileSystemFileHandle>
  getDirectoryHandle: (name: string, options?: { create?: boolean }) => Promise<FileSystemDirectoryHandle>
  removeEntry: (name: string, options?: { recursive?: boolean }) => Promise<void>
  values?: () => AsyncIterableIterator<FileSystemHandle>
}
interface FileSystemWritableFileStream extends WritableStream {
  write: (data: BufferSource | Blob | string) => Promise<void>
  close: () => Promise<void>
}
