// Model Manager - система управления моделями API
class ModelManager {
    constructor() {
        this.models = {};
        this.currentModel = null;
        this.apiKeys = {};
    }

    registerModel(name, config) {
        this.models[name] = {
            name: name,
            endpoint: config.endpoint,
            processMethod: config.processMethod,
            requiredKey: config.requiredKey
        };
    }

    setCurrentModel(name) {
        // Устанавливаем модель даже если она не зарегистрирована
        // Модели используются напрямую через API
        this.currentModel = name;
        this.loadApiKey();
    }

    getCurrentModel() {
        // Возвращаем объект с именем модели, даже если не зарегистрирована
        if (!this.currentModel) {
            return null;
        }
        return {
            name: this.currentModel
        };
    }

    getApiKey(modelName = null) {
        const model = modelName || this.currentModel;
        // Сначала проверяем localStorage
        const storedKey = localStorage.getItem(`api_key_${model}`);
        if (storedKey) {
            return storedKey;
        }
        // Fallback на .env через сервер
        return null;
    }

    saveApiKey(modelName, apiKey) {
        localStorage.setItem(`api_key_${modelName}`, apiKey);
        this.apiKeys[modelName] = apiKey;
    }

    loadApiKey() {
        const model = this.currentModel;
        if (model) {
            const key = this.getApiKey(model);
            if (key) {
                document.getElementById('apiKeyInput').value = key;
            }
        }
    }
}

// Yandex Disk Manager
class YandexDiskManager {
    constructor() {
        this.accessToken = null;
        this.baseUrl = 'https://cloud-api.yandex.net/v1/disk';
    }

    async authorize() {
        // Открываем окно авторизации
        const authWindow = window.open('/auth/yandex', 'yandex_auth', 'width=600,height=700');
        
        // Слушаем сообщения от окна авторизации
        window.addEventListener('message', (event) => {
            if (event.data.type === 'yandex_auth_success') {
                this.setAccessToken(event.data.token);
                authWindow.close();
                // Обновляем UI
                if (window.app) {
                    window.app.checkYandexAuth();
                }
            }
        });
    }

    async checkAuth() {
        // Проверяем сохраненный токен в localStorage
        const savedToken = localStorage.getItem('yandex_disk_token');
        if (savedToken) {
            this.accessToken = savedToken;
            try {
                const response = await fetch(`/api/yandex/check?token=${savedToken}`);
                const data = await response.json();
                if (data.authenticated) {
                    return true;
                }
            } catch (error) {
                // Токен невалиден, удаляем
                localStorage.removeItem('yandex_disk_token');
                this.accessToken = null;
            }
        }
        
        // Если токена в localStorage нет, проверяем токен из .env
        try {
            const response = await fetch('/api/yandex/get-env-token');
            const data = await response.json();
            if (data.has_token && data.valid) {
                // Используем токен из .env (но не сохраняем в localStorage)
                // Сервер будет использовать его автоматически
                return true;
            }
        } catch (error) {
            console.error('Error checking env token:', error);
        }
        
        return false;
    }

    setAccessToken(token) {
        this.accessToken = token;
        localStorage.setItem('yandex_disk_token', token);
    }

    async getFolders() {
        try {
            const tokenParam = this.accessToken ? `?token=${this.accessToken}` : '';
            const response = await fetch(`/api/yandex/folders${tokenParam}`);
            const data = await response.json();
            return data.folders || [];
        } catch (error) {
            console.error('Error fetching folders:', error);
            return [];
        }
    }

    async getFolderFiles(folderPath) {
        try {
            const tokenParam = this.accessToken ? `&token=${this.accessToken}` : '';
            const response = await fetch(`/api/yandex/files?path=${encodeURIComponent(folderPath)}${tokenParam}`);
            const data = await response.json();
            return data.files || [];
        } catch (error) {
            console.error('Error fetching files:', error);
            return [];
        }
    }

    async downloadFile(filePath) {
        try {
            const tokenParam = this.accessToken ? `&token=${this.accessToken}` : '';
            const response = await fetch(`/api/yandex/download?path=${encodeURIComponent(filePath)}${tokenParam}`);
            
            if (!response.ok) {
                throw new Error(`Failed to download file: ${response.status} ${response.statusText}`);
            }
            
            const blob = await response.blob();
            
            // Проверяем, что blob не пустой
            if (blob.size === 0) {
                throw new Error('Downloaded file is empty');
            }
            
            return blob;
        } catch (error) {
            console.error('Error downloading file:', error);
            throw error;
        }
    }

    async uploadFile(filePath, fileBlob) {
        try {
            const formData = new FormData();
            formData.append('file', fileBlob);
            formData.append('path', filePath);
            formData.append('token', this.accessToken || '');

            const response = await fetch('/api/yandex/upload', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error uploading file:', error);
            throw error;
        }
    }

    async createFolder(folderPath) {
        try {
            const formData = new FormData();
            formData.append('path', folderPath);
            formData.append('token', this.accessToken || '');

            const response = await fetch('/api/yandex/create-folder', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
                // Если папка уже существует (409), это нормально
                if (response.status === 409) {
                    return { success: true, path: folderPath, exists: true };
                }
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error creating folder:', error);
            throw error;
        }
    }

    async getPublicFiles(publicUrl) {
        try {
            const response = await fetch(`/api/yandex/public-files?public_url=${encodeURIComponent(publicUrl)}`);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
                throw new Error(errorData.detail || `Ошибка ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data.files || [];
        } catch (error) {
            console.error('Error fetching public files:', error);
            throw error;
        }
    }

    async getStructure(path = "/", lazy = true) {
        try {
            // Если есть токен в localStorage, используем его, иначе сервер возьмет из .env
            const tokenParam = this.accessToken ? `&token=${this.accessToken}` : '';
            const response = await fetch(`/api/yandex/structure?path=${encodeURIComponent(path)}&lazy=${lazy}${tokenParam}`);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
                throw new Error(errorData.detail || `Ошибка ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error fetching structure:', error);
            throw error;
        }
    }

    async getAccountInfo() {
        try {
            // Если есть токен в localStorage, используем его, иначе сервер возьмет из .env
            const tokenParam = this.accessToken ? `?token=${this.accessToken}` : '';
            const response = await fetch(`/api/yandex/account-info${tokenParam}`);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
                throw new Error(errorData.detail || `Ошибка ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error fetching account info:', error);
            throw error;
        }
    }

    async downloadPublicFile(fileUrl) {
        try {
            // Для публичных файлов используем прокси через наш сервер
            const response = await fetch(`/api/yandex/download-public?url=${encodeURIComponent(fileUrl)}`);
            const blob = await response.blob();
            return blob;
        } catch (error) {
            console.error('Error downloading public file:', error);
            throw error;
        }
    }
}

// Image Processor
class ImageProcessor {
    constructor() {
        this.uploadedImage = null;
        this.processedImage = null;
    }

    async processImage(imageFile, modelName, apiKey, prompt = null) {
        const formData = new FormData();
        formData.append('image', imageFile);
        formData.append('model', modelName);
        if (apiKey) {
            formData.append('apiKey', apiKey);
        }
        if (prompt) {
            formData.append('prompt', prompt);
        }

        try {
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Ошибка обработки');
            }

            const blob = await response.blob();
            return blob;
        } catch (error) {
            console.error('Processing error:', error);
            throw error;
        }
    }

    async placeOnTemplate(imageBlob, templatePath, width = 1200, height = 1200) {
        const formData = new FormData();
        formData.append('image', imageBlob);
        formData.append('template', templatePath);
        formData.append('width', width.toString());
        formData.append('height', height.toString());

        try {
            const response = await fetch('/api/place-template', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Ошибка размещения на шаблон');
            }

            const blob = await response.blob();
            return blob;
        } catch (error) {
            console.error('Template placement error:', error);
            throw error;
        }
    }
}

// Main Application
class App {
    constructor() {
        this.modelManager = new ModelManager();
        this.uploadedImageDimensions = null; // Храним размеры загруженного изображения
        this.yandexDisk = new YandexDiskManager();
        this.imageProcessor = new ImageProcessor();
        this.currentFile = null;
        this.currentFileSource = null; // Информация об источнике файла: {type: 'yandex', folderUrl: '...', fileName: '...'} или null
        this.yandexFiles = [];
        this.init();
    }

    init() {
        // Устанавливаем Replicate как модель по умолчанию
        this.modelManager.setCurrentModel('replicate');
        this.setupEventListeners();
        this.setupSliders();
        // Инициализируем панель API ключей после загрузки DOM
        setTimeout(() => {
            this.setupApiKeysPanel();
            this.loadApiKeysFromStorage();
        }, 100);
    }
    
    setupSliders() {
        const widthSlider = document.getElementById('widthSlider');
        const heightSlider = document.getElementById('heightSlider');
        const widthValue = document.getElementById('widthValue');
        const heightValue = document.getElementById('heightValue');
        
        if (widthSlider && widthValue) {
            widthSlider.addEventListener('input', (e) => {
                widthValue.textContent = e.target.value;
            });
        }
        
        if (heightSlider && heightValue) {
            heightSlider.addEventListener('input', (e) => {
                heightValue.textContent = e.target.value;
            });
        }
    }

    setupEventListeners() {
        // Model selection
        document.getElementById('modelSelect').addEventListener('change', (e) => {
            this.modelManager.setCurrentModel(e.target.value);
            // fal-ai/imageutils/rembg не требует prompt
        });

        // File upload
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');

        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = 'var(--primary-color)';
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.style.borderColor = 'var(--border-color)';
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = 'var(--border-color)';
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.handleFileSelect(files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleFileSelect(e.target.files[0]);
            }
        });

        // Remove image
        document.getElementById('removeImageBtn').addEventListener('click', () => {
            this.clearUpload();
        });

        // Process button
        document.getElementById('processBtn').addEventListener('click', () => {
            this.processImage();
        });

        // Download button
        document.getElementById('downloadBtn').addEventListener('click', () => {
            this.downloadProcessed();
        });

        // Yandex Disk - загрузка файлов из публичной папки
        document.getElementById('loadYandexFilesBtn').addEventListener('click', () => {
            this.loadYandexFiles();
        });

        // Открытие/закрытие боковой панели
        document.getElementById('openSidebarBtn').addEventListener('click', () => {
            this.loadYandexStructure();
        });

        document.getElementById('closeSidebar').addEventListener('click', () => {
            this.closeSidebar();
        });

        document.getElementById('sidebarOverlay').addEventListener('click', () => {
            this.closeSidebar();
        });
    }

    async loadYandexFiles() {
        const url = document.getElementById('yandexUrlInput').value.trim();
        if (!url) {
            this.showError('Введите URL папки Яндекс Диска');
            return;
        }

        const sidebarLoading = document.getElementById('sidebarLoading');
        const sidebarFiles = document.getElementById('sidebarFiles');
        
        sidebarLoading.style.display = 'block';
        sidebarFiles.innerHTML = '';
        this.openSidebar();

        try {
            const files = await this.yandexDisk.getPublicFiles(url);
            this.yandexFiles = files;
            this.renderSidebarFiles(files);
            sidebarLoading.style.display = 'none';
            this.showMessage(`Загружено ${files.length} файлов`, 'success');
        } catch (error) {
            sidebarLoading.style.display = 'none';
            sidebarFiles.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error-color);">Ошибка: ${error.message || 'Не удалось загрузить файлы'}</div>`;
            this.showError(error.message || 'Ошибка загрузки файлов');
        }
    }

    async loadYandexStructure() {
        const hasToken = await this.yandexDisk.checkAuth();
        if (!hasToken) {
            this.showError('Необходима авторизация в Яндекс Диске. Используйте кнопку авторизации.');
            return;
        }

        const sidebarLoading = document.getElementById('sidebarLoading');
        const sidebarFiles = document.getElementById('sidebarFiles');
        const accountInfo = document.getElementById('sidebarAccountInfo');
        
        sidebarLoading.style.display = 'block';
        sidebarFiles.innerHTML = '';
        this.openSidebar();

        try {
            // Загружаем информацию об аккаунте
            try {
                const accountData = await this.yandexDisk.getAccountInfo();
                document.getElementById('accountDisplayName').textContent = accountData.display_name || accountData.login;
                document.getElementById('accountUsedSpace').textContent = `${accountData.used_space_gb} GB / ${accountData.total_space_gb} GB`;
                accountInfo.style.display = 'block';
            } catch (e) {
                console.error('Error loading account info:', e);
            }

            // Загружаем только корневой уровень (только названия, без загрузки файлов)
            sidebarLoading.textContent = 'Загрузка списка...';
            const structureData = await this.yandexDisk.getStructure("/", true);
            this.renderSidebarStructure(structureData.structure);
            sidebarLoading.style.display = 'none';
        } catch (error) {
            sidebarLoading.style.display = 'none';
            sidebarFiles.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error-color);">Ошибка: ${error.message || 'Не удалось загрузить структуру'}</div>`;
            this.showError(error.message || 'Ошибка загрузки структуры');
        }
    }

    renderSidebarStructure(structure, container = null, depth = 0) {
        const sidebarFiles = container || document.getElementById('sidebarFiles');
        
        if (!structure || structure.length === 0) {
            if (container) {
                container.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-secondary); font-size: 13px;">Пусто</div>';
            } else {
                sidebarFiles.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-secondary);">Папки не найдены</div>';
            }
            return;
        }

        const createStructureItem = (item, currentDepth) => {
            const itemDiv = document.createElement('div');
            itemDiv.className = `sidebar-structure-item ${item.type}`;
            itemDiv.style.paddingLeft = `${currentDepth * 16}px`;
            
            if (item.type === 'dir') {
                // Для папок всегда показываем иконку и возможность развернуть
                const hasChildren = item.has_children !== false; // Предполагаем, что есть дети
                itemDiv.innerHTML = `
                    <div class="structure-item-header" data-path="${item.path}">
                        <span class="structure-icon">📁</span>
                        <span class="structure-name">${item.name}</span>
                        <span class="structure-toggle">▼</span>
                        <span class="structure-loading" style="display: none; margin-left: 8px; font-size: 10px;">⏳</span>
                    </div>
                    <div class="structure-children" style="display: none;"></div>
                `;
                
                // Обработчик клика для папки
                const header = itemDiv.querySelector('.structure-item-header');
                const childrenDiv = itemDiv.querySelector('.structure-children');
                const toggle = itemDiv.querySelector('.structure-toggle');
                const loading = itemDiv.querySelector('.structure-loading');
                
                header.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    
                    if (childrenDiv.style.display === 'none') {
                        // Разворачиваем папку
                        childrenDiv.style.display = 'block';
                        toggle.textContent = '▲';
                        
                        // Если содержимое еще не загружено, загружаем его
                        if (childrenDiv.children.length === 0 && item.children === null) {
                            loading.style.display = 'inline';
                            toggle.style.display = 'none';
                            
                            try {
                                const folderData = await this.yandexDisk.getStructure(item.path, true);
                                item.children = folderData.structure || [];
                                
                                // Рендерим загруженное содержимое
                                if (item.children.length > 0) {
                                    this.renderSidebarStructure(item.children, childrenDiv, currentDepth + 1);
                                } else {
                                    childrenDiv.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-secondary); font-size: 13px;">Пусто</div>';
                                }
                            } catch (error) {
                                console.error('Error loading folder:', error);
                                childrenDiv.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--error-color); font-size: 13px;">Ошибка загрузки</div>`;
                            } finally {
                                loading.style.display = 'none';
                                toggle.style.display = 'inline';
                            }
                        } else if (item.children && item.children.length > 0) {
                            // Содержимое уже загружено, просто рендерим
                            this.renderSidebarStructure(item.children, childrenDiv, currentDepth + 1);
                        }
                    } else {
                        // Сворачиваем папку
                        childrenDiv.style.display = 'none';
                        toggle.textContent = '▼';
                    }
                });
            } else {
                // Файл - показываем только название, загружаем при клике
                itemDiv.innerHTML = `
                    <div class="structure-item-header structure-file" data-path="${item.path}" data-name="${item.name}">
                        <span class="structure-icon">📄</span>
                        <span class="structure-name">${item.name}</span>
                    </div>
                `;
                
                // Обработчик клика для файла - загружаем в окно ЗАГРУЗКА
                const header = itemDiv.querySelector('.structure-item-header');
                header.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await this.loadFileToUpload(item);
                });
            }
            
            return itemDiv;
        };

        // Рендерим элементы порциями для лучшей производительности
        const BATCH_SIZE = 20;
        let index = 0;
        
        const renderBatch = () => {
            const end = Math.min(index + BATCH_SIZE, structure.length);
            for (let i = index; i < end; i++) {
                const item = structure[i];
                const itemDiv = createStructureItem(item, depth);
                sidebarFiles.appendChild(itemDiv);
            }
            index = end;
            
            // Если есть еще элементы, рендерим следующую порцию
            if (index < structure.length) {
                setTimeout(renderBatch, 10); // Небольшая задержка для неблокирующего рендеринга
            }
        };
        
        renderBatch();
    }

    async loadFileToUpload(file) {
        try {
            // Показываем индикатор загрузки в окне ЗАГРУЗКА
            const uploadArea = document.getElementById('uploadArea');
            const uploadPreview = document.getElementById('uploadPreview');
            const processBtn = document.getElementById('processBtn');
            
            if (!uploadArea || !uploadPreview || !processBtn) {
                throw new Error('Не найдены необходимые элементы интерфейса');
            }
            
            // Скрываем область загрузки и показываем превью с загрузкой
            uploadArea.style.display = 'none';
            uploadPreview.style.display = 'block';
            processBtn.style.display = 'none';
            
            // Показываем индикатор загрузки
            uploadPreview.innerHTML = `
                <div class="loading" style="display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 40px;">
                    <div class="spinner"></div>
                    <p style="color: var(--text-secondary);">Загрузка ${file.name}...</p>
                </div>
            `;
            
            // Скачиваем файл через OAuth API
            const blob = await this.yandexDisk.downloadFile(file.path);
            
            // Определяем тип файла на основе расширения
            const fileName = file.name || 'image.jpg';
            let mimeType = blob.type;
            if (!mimeType || mimeType === 'application/octet-stream') {
                // Определяем MIME тип по расширению
                const ext = fileName.toLowerCase().split('.').pop();
                const mimeTypes = {
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'png': 'image/png',
                    'gif': 'image/gif',
                    'webp': 'image/webp'
                };
                mimeType = mimeTypes[ext] || 'image/jpeg';
            }
            
            // Создаем File объект из blob с правильным типом
            const fileObj = new File([blob], fileName, { type: mimeType });
            
            // Сохраняем информацию об источнике
            this.currentFileSource = {
                type: 'yandex',
                folderUrl: file.path,
                fileName: fileName,
                originalFile: file
            };
            
            // Загружаем изображение в превью
            const reader = new FileReader();
            reader.onerror = (error) => {
                console.error('FileReader error:', error);
                uploadPreview.innerHTML = `
                    <div style="color: var(--error-color); padding: 20px; text-align: center;">
                        Ошибка чтения файла<br>
                        <button id="removeImageBtn" class="btn btn-small" style="margin-top: 10px;">Закрыть</button>
                    </div>
                `;
                const closeBtn = document.getElementById('removeImageBtn');
                if (closeBtn) {
                    closeBtn.addEventListener('click', () => {
                        this.clearUpload();
                    });
                }
            };
            reader.onload = (e) => {
                // Проверяем, что data URL не пустой
                if (!e.target.result || e.target.result.length < 100) {
                    console.error('Invalid image data, length:', e.target.result ? e.target.result.length : 0);
                    uploadPreview.innerHTML = `
                        <div style="color: var(--error-color); padding: 20px; text-align: center;">
                            Неверный формат изображения<br>
                            <small>Размер файла: ${(fileObj.size / 1024).toFixed(2)} KB</small><br>
                            <button id="removeImageBtn" class="btn btn-small" style="margin-top: 10px;">Закрыть</button>
                        </div>
                    `;
                    const closeBtn = document.getElementById('removeImageBtn');
                    if (closeBtn) {
                        closeBtn.addEventListener('click', () => {
                            this.clearUpload();
                        });
                    }
                    return;
                }
                
                // Обновляем превью с изображением
                uploadPreview.innerHTML = `
                    <img id="uploadImage" class="preview-image" src="${e.target.result}" alt="Загруженное фото">
                    <button id="removeImageBtn" class="btn btn-small">Удалить</button>
                `;
                
                // Восстанавливаем обработчик для кнопки удаления
                const removeBtn = document.getElementById('removeImageBtn');
                if (removeBtn) {
                    removeBtn.addEventListener('click', () => {
                        this.clearUpload();
                    });
                }
                
                // Показываем кнопку обработки
                if (processBtn) {
                    processBtn.style.display = 'block';
                }
                
                // Проверяем, загрузилось ли изображение и сохраняем размеры
                const img = document.getElementById('uploadImage');
                if (img) {
                    // Используем setTimeout, чтобы получить размеры после применения CSS
                    const updateDimensions = () => {
                        if (img.complete) {
                            const rect = img.getBoundingClientRect();
                            console.log('Изображение успешно загружено, размер:', img.naturalWidth, 'x', img.naturalHeight, 
                                      'отображается:', rect.width, 'x', rect.height);
                            // Сохраняем отображаемые размеры изображения для использования в ОБРАБОТКА
                            this.uploadedImageDimensions = {
                                width: rect.width,
                                height: rect.height,
                                naturalWidth: img.naturalWidth,
                                naturalHeight: img.naturalHeight
                            };
                        }
                    };
                    img.onload = () => {
                        setTimeout(updateDimensions, 100); // Небольшая задержка для применения CSS
                    };
                    // Если изображение уже загружено
                    if (img.complete) {
                        setTimeout(updateDimensions, 100);
                    }
                    img.onerror = (error) => {
                        console.error('Ошибка загрузки изображения:', error);
                        console.error('Data URL length:', e.target.result ? e.target.result.length : 0);
                        console.error('File size:', fileObj.size, 'bytes');
                        console.error('File type:', fileObj.type);
                        uploadPreview.innerHTML = `
                            <div style="color: var(--error-color); padding: 20px; text-align: center;">
                                Ошибка отображения изображения<br>
                                <small>Размер файла: ${(fileObj.size / 1024).toFixed(2)} KB</small><br>
                                <small>Тип: ${fileObj.type || 'неизвестно'}</small><br>
                                <button id="removeImageBtn" class="btn btn-small" style="margin-top: 10px;">Закрыть</button>
                            </div>
                        `;
                        const closeBtn = document.getElementById('removeImageBtn');
                        if (closeBtn) {
                            closeBtn.addEventListener('click', () => {
                                this.clearUpload();
                            });
                        }
                    };
                }
            };
            reader.readAsDataURL(fileObj);
            
            this.currentFile = fileObj;
            
            // Закрываем боковую панель
            this.closeSidebar();
        } catch (error) {
            // Восстанавливаем интерфейс при ошибке
            document.getElementById('uploadArea').style.display = 'flex';
            document.getElementById('uploadPreview').style.display = 'none';
            this.showError('Ошибка загрузки файла: ' + error.message);
        }
    }

    renderSidebarFiles(files) {
        const sidebarFiles = document.getElementById('sidebarFiles');
        const sidebarLoading = document.getElementById('sidebarLoading');
        
        sidebarLoading.style.display = 'none';
        sidebarFiles.innerHTML = '';

        if (files.length === 0) {
            sidebarFiles.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-secondary);">Файлы не найдены</div>';
            return;
        }

        // Lazy evaluation: создаем контейнеры для всех файлов, но загружаем контент только для видимых
        const ITEMS_PER_BATCH = 20; // Загружаем по 20 элементов за раз
        let renderedCount = 0;
        
        // Функция для создания элемента файла
        const createFileItem = (file, index) => {
            const fileItem = document.createElement('div');
            fileItem.className = 'sidebar-file-item';
            fileItem.dataset.index = index;
            fileItem.dataset.loaded = 'false';
            
            // Плейсхолдер для ленивой загрузки
            fileItem.innerHTML = `
                <div class="sidebar-file-name">${file.name || 'Загрузка...'}</div>
                <div class="sidebar-file-path" style="opacity: 0.6;">${file.path || file.url || ''}</div>
            `;
            
            fileItem.addEventListener('click', () => {
                this.selectFileFromSidebar(file, fileItem);
            });
            
            return fileItem;
        };

        // Создаем все элементы сразу (для правильной прокрутки), но с плейсхолдерами
        files.forEach((file, index) => {
            const fileItem = createFileItem(file, index);
            sidebarFiles.appendChild(fileItem);
        });

        // Intersection Observer для lazy loading видимых элементов
        const observerOptions = {
            root: sidebarFiles,
            rootMargin: '50px', // Загружаем за 50px до появления в viewport
            threshold: 0.1
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && entry.target.dataset.loaded === 'false') {
                    const index = parseInt(entry.target.dataset.index);
                    const file = files[index];
                    
                    if (file) {
                        // Обновляем контент элемента
                        entry.target.innerHTML = `
                            <div class="sidebar-file-name">${file.name}</div>
                            <div class="sidebar-file-path">${file.path || file.url || ''}</div>
                        `;
                        entry.target.dataset.loaded = 'true';
                    }
                }
            });
        }, observerOptions);

        // Наблюдаем за всеми элементами
        Array.from(sidebarFiles.children).forEach(item => {
            observer.observe(item);
        });

        // Также загружаем первые элементы сразу (без ожидания прокрутки)
        const initialItems = Array.from(sidebarFiles.children).slice(0, ITEMS_PER_BATCH);
        initialItems.forEach(item => {
            const index = parseInt(item.dataset.index);
            const file = files[index];
            if (file && item.dataset.loaded === 'false') {
                item.innerHTML = `
                    <div class="sidebar-file-name">${file.name}</div>
                    <div class="sidebar-file-path">${file.path || file.url || ''}</div>
                `;
                item.dataset.loaded = 'true';
            }
        });
    }

    async selectFileFromSidebar(file, fileItem) {
        // Убираем выделение с других элементов
        document.querySelectorAll('.sidebar-file-item').forEach(item => {
            item.classList.remove('selected');
        });
        fileItem.classList.add('selected');

        try {
            // Скачиваем файл
            const blob = await this.yandexDisk.downloadPublicFile(file.url || file.path);
            
            // Создаем File объект из blob
            const fileName = file.name || 'image.jpg';
            const fileObj = new File([blob], fileName, { type: blob.type || 'image/jpeg' });
            
            // Сохраняем информацию об источнике файла
            const yandexUrl = document.getElementById('yandexUrlInput').value.trim();
            this.currentFileSource = {
                type: 'yandex',
                folderUrl: yandexUrl,
                fileName: fileName,
                originalFile: file
            };
            
            // Загружаем в интерфейс
            this.handleFileSelect(fileObj);
            
            // Закрываем боковую панель
            this.closeSidebar();
        } catch (error) {
            this.showError('Ошибка загрузки файла: ' + error.message);
        }
    }

    openSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        sidebar.classList.add('open');
        overlay.classList.add('active');
    }

    closeSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
    }

    handleFileSelect(file) {
        if (!file.type.startsWith('image/')) {
            this.showError('Пожалуйста, выберите изображение');
            return;
        }

        this.currentFile = file;
        // Если файл выбран локально (не из Yandex Disk), сбрасываем источник
        if (!this.currentFileSource || this.currentFileSource.type !== 'yandex') {
            this.currentFileSource = null;
        }
        
        const reader = new FileReader();
        reader.onload = (e) => {
            const uploadImg = document.getElementById('uploadImage');
            uploadImg.src = e.target.result;
            // Сохраняем размеры изображения после загрузки (фактические отображаемые размеры)
            const updateDimensions = () => {
                if (uploadImg.complete) {
                    const rect = uploadImg.getBoundingClientRect();
                    this.uploadedImageDimensions = {
                        width: rect.width,
                        height: rect.height,
                        naturalWidth: uploadImg.naturalWidth,
                        naturalHeight: uploadImg.naturalHeight
                    };
                }
            };
            uploadImg.onload = () => {
                setTimeout(updateDimensions, 100); // Небольшая задержка для применения CSS
            };
            document.getElementById('uploadArea').style.display = 'none';
            document.getElementById('uploadPreview').style.display = 'block';
            document.getElementById('processBtn').style.display = 'block';
        };
        reader.readAsDataURL(file);
    }

    clearUpload() {
        this.currentFile = null;
        this.currentFileSource = null;
        this.uploadedImageDimensions = null;
        document.getElementById('fileInput').value = '';
        document.getElementById('uploadArea').style.display = 'flex';
        document.getElementById('uploadPreview').style.display = 'none';
        document.getElementById('processBtn').style.display = 'none';
        const processedImg = document.getElementById('processedImage');
        processedImg.style.display = 'none';
        // Сбрасываем размеры обработанного изображения
        processedImg.style.width = '';
        processedImg.style.height = '';
        document.getElementById('downloadBtn').style.display = 'none';
    }

    async processImage() {
        if (!this.currentFile) {
            this.showError('Сначала загрузите изображение');
            return;
        }

        const model = this.modelManager.getCurrentModel();
        if (!model) {
            this.showError('Выберите модель API');
            return;
        }

        const apiKey = this.modelManager.getApiKey();
        // Если ключ не найден в localStorage, сервер возьмет из .env
        // Для FAL, FAL Object Removal и Replicate не требуем ключ в localStorage - он автоматически берется из .env
        if (!apiKey && model.name !== 'fal' && model.name !== 'fal_object_removal' && model.name !== 'replicate') {
            this.showError('API ключ не найден. Установите его в панели API ключей или в .env файле');
            return;
        }

        this.showLoading(true);
        this.hideError();

        try {
            // fal-ai/imageutils/rembg не требует prompt
            let prompt = null;

            // Обработка изображения
            const processedBlob = await this.imageProcessor.processImage(
                this.currentFile,
                model.name,
                apiKey,
                prompt
            );

            // Получаем фактические отображаемые размеры изображения в ЗАГРУЗКА
            const uploadImg = document.getElementById('uploadImage');
            let templateWidth = 1200;
            let templateHeight = 1200;
            let displayWidth = null;
            let displayHeight = null;
            
            if (uploadImg && uploadImg.complete) {
                const rect = uploadImg.getBoundingClientRect();
                // Используем натуральные размеры изображения для template (w pikselach)
                // Ale sprawdzamy też wyświetlane wymiary
                if (this.uploadedImageDimensions && this.uploadedImageDimensions.naturalWidth && this.uploadedImageDimensions.naturalHeight) {
                    // Используем натуральные размеры для template
                    templateWidth = this.uploadedImageDimensions.naturalWidth;
                    templateHeight = this.uploadedImageDimensions.naturalHeight;
                    // А для wyświetlania używamy wyświetlanych wymiarów
                    displayWidth = rect.width;
                    displayHeight = rect.height;
                } else {
                    // Fallback: używamy wyświetlanych wymiarów
                    templateWidth = Math.round(rect.width);
                    templateHeight = Math.round(rect.height);
                    displayWidth = rect.width;
                    displayHeight = rect.height;
                }
            } else {
                // Fallback: używamy размеров из слайдеров
                const widthSlider = document.getElementById('widthSlider');
                const heightSlider = document.getElementById('heightSlider');
                templateWidth = widthSlider ? parseInt(widthSlider.value) : 1200;
                templateHeight = heightSlider ? parseInt(heightSlider.value) : 1200;
            }
            
            // Размещение на шаблон с размерами оригинала
            const templateBlob = await this.imageProcessor.placeOnTemplate(
                processedBlob,
                'default',
                templateWidth,
                templateHeight
            );

            // Отображение результата
            const url = URL.createObjectURL(templateBlob);
            const processedImg = document.getElementById('processedImage');
            processedImg.src = url;
            processedImg.style.display = 'block';
            
            // Устанавливаем точно такие же размеры отображения, как у изображения в ЗАГРУЗКА
            if (displayWidth !== null && displayHeight !== null) {
                processedImg.style.width = `${displayWidth}px`;
                processedImg.style.height = `${displayHeight}px`;
                processedImg.style.maxWidth = `${displayWidth}px`;
                processedImg.style.maxHeight = `${displayHeight}px`;
                processedImg.style.objectFit = 'contain';
            } else if (this.uploadedImageDimensions) {
                // Fallback: używamy zapisanych wymiarów
                processedImg.style.width = `${this.uploadedImageDimensions.width}px`;
                processedImg.style.height = `${this.uploadedImageDimensions.height}px`;
                processedImg.style.maxWidth = `${this.uploadedImageDimensions.width}px`;
                processedImg.style.maxHeight = `${this.uploadedImageDimensions.height}px`;
                processedImg.style.objectFit = 'contain';
            }
            
            document.getElementById('downloadBtn').style.display = 'block';
            this.processedImage = templateBlob;

            // Автоматическое сохранение на Яндекс Диск, если файл оттуда
            if (this.currentFileSource && this.currentFileSource.type === 'yandex') {
                try {
                    await this.saveProcessedToYandex(templateBlob);
                } catch (error) {
                    console.error('Ошибка сохранения на Яндекс Диск:', error);
                    // Не показываем ошибку пользователю, так как файл уже обработан
                }
            }

            this.showLoading(false);
        } catch (error) {
            this.showLoading(false);
            this.showError(error.message || 'Ошибка обработки изображения');
        }
    }

    async processFolder() {
        const folderPath = document.getElementById('folderSelect').value;
        if (!folderPath) {
            this.showError('Выберите папку');
            return;
        }

        const model = this.modelManager.getCurrentModel();
        if (!model) {
            this.showError('Выберите модель API');
            return;
        }

        const apiKey = this.modelManager.getApiKey();
        // Для FAL, FAL Object Removal и Replicate не требуем ключ в localStorage - он автоматически берется из .env
        if (!apiKey && model.name !== 'fal' && model.name !== 'fal_object_removal' && model.name !== 'replicate') {
            this.showError('API ключ не найден. Установите его в панели API ключей или в .env файле');
            return;
        }

        // Получаем список файлов в папке
        const files = await this.yandexDisk.getFolderFiles(folderPath);
        const imageFiles = files.filter(f => 
            f.mime_type && f.mime_type.startsWith('image/')
        );

        if (imageFiles.length === 0) {
            this.showError('В папке нет изображений');
            return;
        }

        // Создаем папку "Обработанные"
        const processedFolderPath = folderPath + '/Обработанные';
        await this.yandexDisk.createFolder(processedFolderPath);

        // Показываем прогресс
        document.getElementById('batchProgress').style.display = 'block';
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');

        let processed = 0;
        const total = imageFiles.length;

        // Обрабатываем каждое изображение
        for (const file of imageFiles) {
            try {
                // Скачиваем файл
                const fileBlob = await this.yandexDisk.downloadFile(file.path);

                // fal-ai/imageutils/rembg не требует prompt
                let prompt = null;

                // Обрабатываем
                const processedBlob = await this.imageProcessor.processImage(
                    fileBlob,
                    model.name,
                    apiKey,
                    prompt
                );

                // Получаем выбранный формат
                const formatSelect = document.getElementById('formatSelect');
                const selectedFormat = formatSelect ? formatSelect.value : '1:1';
                
                // Размещаем на шаблон
                const templateBlob = await this.imageProcessor.placeOnTemplate(
                    processedBlob,
                    'default',
                    selectedFormat
                );

                // Сохраняем в папку "Обработанные"
                const fileName = file.name.replace(/\.[^/.]+$/, '') + '.png';
                const savePath = processedFolderPath + '/' + fileName;
                await this.yandexDisk.uploadFile(savePath, templateBlob);

                processed++;
                const progress = (processed / total) * 100;
                progressFill.style.width = progress + '%';
                progressText.textContent = `${processed} / ${total}`;
            } catch (error) {
                console.error(`Error processing ${file.name}:`, error);
                // Продолжаем обработку остальных файлов
            }
        }

        this.showMessage(`Обработано ${processed} из ${total} изображений`, 'success');
        document.getElementById('batchProgress').style.display = 'none';
    }

    async saveProcessedToYandex(templateBlob) {
        // Проверяем, есть ли токен для загрузки
        const hasToken = await this.yandexDisk.checkAuth();
        if (!hasToken) {
            console.log('Токен Яндекс Диска не найден, пропускаем автоматическое сохранение');
            return;
        }

        if (!this.currentFileSource || this.currentFileSource.type !== 'yandex') {
            return;
        }

        try {
            // Извлекаем ID папки из URL
            const folderUrl = this.currentFileSource.folderUrl;
            const match = folderUrl.match(/\/d\/([^/?]+)/);
            if (!match) {
                console.error('Не удалось извлечь ID папки из URL');
                return;
            }

            const folderId = match[1];
            
            // Пробуем определить имя папки из оригинального файла или используем ID
            // Для публичных папок используем ID как имя папки
            // Создаем структуру: /{folderId}/Обработанные
            const processedFolderPath = `/${folderId}/Обработанные`;
            
            // Создаем папку если её нет
            try {
                await this.yandexDisk.createFolder(processedFolderPath);
            } catch (error) {
                // Игнорируем ошибку если папка уже существует (409)
                if (error.message && !error.message.includes('409')) {
                    console.log('Ошибка создания папки:', error);
                }
            }

            // Генерируем имя файла
            const originalFileName = this.currentFileSource.fileName || 'image.jpg';
            const fileName = originalFileName.replace(/\.[^/.]+$/, '') + '.png';
            const savePath = `${processedFolderPath}/${fileName}`;

            // Загружаем файл
            await this.yandexDisk.uploadFile(savePath, templateBlob);
            console.log(`Файл сохранен на Яндекс Диск: ${savePath}`);
            this.showMessage(`Файл сохранен в папку "Обработанные" на Яндекс Диске`, 'success');
        } catch (error) {
            console.error('Ошибка сохранения на Яндекс Диск:', error);
            // Не бросаем ошибку дальше, чтобы не прерывать процесс
        }
    }

    downloadProcessed() {
        if (!this.processedImage) return;

        const url = URL.createObjectURL(this.processedImage);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'processed.png';
        a.click();
        URL.revokeObjectURL(url);
    }

    showLoading(show) {
        const loadingEl = document.getElementById('loadingIndicator');
        const processBtn = document.getElementById('processBtn');
        if (loadingEl) {
            loadingEl.style.display = show ? 'flex' : 'none';
        }
        if (processBtn) {
            processBtn.disabled = show;
        }
    }

    showError(message) {
        const errorEl = document.getElementById('errorMessage');
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        setTimeout(() => {
            errorEl.style.display = 'none';
        }, 5000);
    }

    showMessage(message, type = 'success') {
        // Показываем сообщение через error message, но с другим стилем
        const errorEl = document.getElementById('errorMessage');
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        errorEl.style.borderColor = type === 'success' ? 'var(--success-color)' : 'var(--error-color)';
        errorEl.style.color = type === 'success' ? 'var(--success-color)' : 'var(--error-color)';
        setTimeout(() => {
            errorEl.style.display = 'none';
        }, 3000);
    }

    hideError() {
        document.getElementById('errorMessage').style.display = 'none';
    }

    setupApiKeysPanel() {
        const panel = document.getElementById('apiKeysPanel');
        const toggle = document.getElementById('apiKeysToggle');
        const content = document.getElementById('apiKeysContent');

        // Переключение панели
        toggle.addEventListener('click', () => {
            panel.classList.toggle('expanded');
            panel.classList.toggle('collapsed');
        });

        // Сохранение ключей
        document.querySelectorAll('.api-key-save').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const model = e.target.dataset.model;
                const modelInputMap = {
                    'removebg': 'apiKeyRemovebg',
                    'clipdrop': 'apiKeyClipdrop',
                    'replicate': 'apiKeyReplicate',
                    'fal': 'apiKeyFal',
                    'fal_object_removal': 'apiKeyFalObjectRemoval'
                };
                const inputId = modelInputMap[model] || `apiKey${model.charAt(0).toUpperCase() + model.slice(1)}`;
                const input = document.getElementById(inputId);
                const apiKey = input.value.trim();
                
                if (apiKey) {
                    this.modelManager.saveApiKey(model, apiKey);
                    this.showMessage(`API ключ для ${model} сохранен`, 'success');
                    input.value = ''; // Очищаем поле после сохранения
                    input.placeholder = `**** (сохранен)`;
                } else {
                    this.showError('Введите API ключ');
                }
            });
        });
    }

    loadApiKeysFromStorage() {
        const modelInputMap = {
            'removebg': 'apiKeyRemovebg',
            'clipdrop': 'apiKeyClipdrop',
            'replicate': 'apiKeyReplicate',
            'fal': 'apiKeyFal',
            'fal_object_removal': 'apiKeyFalObjectRemoval'
        };
        
        Object.entries(modelInputMap).forEach(([model, inputId]) => {
            const key = this.modelManager.getApiKey(model);
            if (key) {
                const input = document.getElementById(inputId);
                if (input) {
                    // Скрываем ключ за ** для безопасности
                    input.placeholder = `**** (сохранен)`;
                }
            }
        });
    }
}

// Инициализация приложения
document.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
});

