package io.github.senitage.kit

import io.github.senitage.kit.core.Store
import java.io.File

/** The chat's history and outbox, in the app's own files folder. */
class FileStore(private val folder: File) : Store {
    override fun read(name: String): String? = try {
        File(folder, name).takeIf { it.isFile }?.readText()
    } catch (e: Exception) {
        null
    }

    override fun write(name: String, text: String) {
        folder.mkdirs()
        val file = File(folder, name)
        val temp = File(folder, "$name.tmp")
        temp.writeText(text)
        if (!temp.renameTo(file)) {
            file.writeText(text)
            temp.delete()
        }
    }
}
