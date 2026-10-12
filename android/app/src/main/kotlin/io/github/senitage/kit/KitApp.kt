package io.github.senitage.kit

import android.app.Application

class KitApp : Application() {
    lateinit var kit: Kit
        private set

    override fun onCreate() {
        super.onCreate()
        Nudges.setUp(this)
        Notifier.makeChannels(this)
        kit = Kit(this)
        CatchUpWorker.schedule(this)
    }
}
