# Tâches planifiées Windows de l'oracle :
#   « Oracle - releve horaire » : un relevé toutes les heures, à l'heure pile ;
#   « Oracle - point matinal »  : le point du jour à 7 h 10 (après le relevé de 7 h).
# Usage :
#   powershell -File outils\planifier.ps1                    # état des deux tâches
#   powershell -File outils\planifier.ps1 installer          # créer ou mettre à jour
#   powershell -File outils\planifier.ps1 lancer [releve|point]
#   powershell -File outils\planifier.ps1 retirer            # supprimer les deux
#
# Compte courant, session ouverte seulement (aucun mot de passe enregistré),
# pythonw : pas de fenêtre. Le compte rendu va dans oracle.log.
# Ce fichier doit rester en UTF-8 avec BOM (PowerShell 5.1).

param(
    [ValidateSet('etat', 'installer', 'lancer', 'retirer')][string]$Action = 'etat',
    [ValidateSet('releve', 'point')][string]$Quoi = 'releve'
)

$ErrorActionPreference = 'Stop'
$racine = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TACHES = [ordered]@{
    releve = @{ Nom = 'Oracle - releve horaire'; Script = 'collecteur.py' }
    point  = @{ Nom = 'Oracle - point matinal';  Script = 'point_matinal.py' }
}

function Afficher-Etat {
    foreach ($t in $TACHES.Values) {
        $tache = Get-ScheduledTask -TaskName $t.Nom -ErrorAction SilentlyContinue
        if (-not $tache) { Write-Output "Aucune tâche « $($t.Nom) »."; continue }
        $info = Get-ScheduledTaskInfo -TaskName $t.Nom
        Write-Output "$($t.Nom) ($($tache.State))"
        Write-Output "  Commande : $($tache.Actions[0].Execute) $($tache.Actions[0].Arguments)"
        Write-Output "  Dernier  : $($info.LastRunTime)  (code $($info.LastTaskResult))"
        Write-Output "  Prochain : $($info.NextRunTime)"
    }
    $log = Join-Path $racine 'oracle.log'
    if (Test-Path $log) {
        Write-Output "--- oracle.log (fin) ---"
        Get-Content $log -Tail 4 -Encoding UTF8
    }
}

function Installer([hashtable]$t, $declencheur, [int]$minutes) {
    $python = (Get-Command python -ErrorAction Stop).Source
    $pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
    if (-not (Test-Path $pythonw)) { throw "pythonw.exe introuvable à côté de $python" }
    # Pas « $action » : PowerShell ignore la casse, ce serait le paramètre $Action.
    $commande = New-ScheduledTaskAction -Execute $pythonw `
        -Argument "$($t.Script) --journal oracle.log" -WorkingDirectory $racine
    $reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $minutes)
    $compte = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
    Register-ScheduledTask -TaskName $t.Nom -Action $commande -Trigger $declencheur `
        -Settings $reglages -Principal $compte -Force `
        -Description "Oracle ($racine). Voir outils\planifier.ps1." | Out-Null
}

switch ($Action) {
    'installer' {
        $heurePile = (Get-Date).Date.AddHours((Get-Date).Hour + 1)
        Installer $TACHES.releve (New-ScheduledTaskTrigger -Once -At $heurePile `
            -RepetitionInterval (New-TimeSpan -Hours 1)) 15
        Installer $TACHES.point (New-ScheduledTaskTrigger -Daily -At '07:10') 15
        Write-Output "Tâches installées."
        Afficher-Etat
    }
    'lancer' {
        Start-ScheduledTask -TaskName $TACHES[$Quoi].Nom
        Write-Output "« $($TACHES[$Quoi].Nom) » lancée. Suivre : outils\planifier.ps1"
    }
    'retirer' {
        foreach ($t in $TACHES.Values) {
            if (Get-ScheduledTask -TaskName $t.Nom -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $t.Nom -Confirm:$false
                Write-Output "Retirée : $($t.Nom)"
            }
        }
    }
    'etat' { Afficher-Etat }
}
