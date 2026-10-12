package io.github.senitage.kit

import android.app.Application

class KitApp : Application() {
    lateinit var kit: Kit
        private set

    override fun onCreate() {
        super.onCreate()
        kit = Kit(this)
    }
}
