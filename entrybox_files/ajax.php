<?php
	if (isset($_POST) && isset($_POST["function"])) {
		$function=$_POST["function"];
		//echo "function = ".$function;
		switch ($function) {

			case 'diag':
				diag();
				break;
			case 'shutdown':
				shutdown();
				break;
			case 'reboot':
				reboot();
				break;
			case 'restart_service':
				restart_service();
				break;
			case 'stop_service':
				stop_service();
				break;
			default:
				echo "not implemented";
			break;
		}
	} else {
		echo "not implemented";
	}

function diag() {
	$cmd = $_POST["cmd"] ?? "";
	$cmd = trim($cmd);

	$out = [];
	$rc = 0;
	exec($cmd . " 2>&1", $out, $rc);

	header("Content-Type: application/json; charset=uft-8");
	echo json_encode([
		"cmd" => $cmd,
		"output" => $out,
	], JSON_UNESCAPED_UNICODE);


	//header("Content-Type: application/json; charset=utf-8");
	//echo json_encode(["cmd"=>$cmd, "output"=>$out], JSON_UNESCAPED_UNICODE);
}

function shutdown() {
	system("date >> /var/log/korona/remote.log");
	system("echo 'shutdown initiated' >> /var/log/korona/remote.log");
	system("sudo /opt/korona/bin/shutdown.sh >> /var/log/korona/remote.log ");
}

function reboot() {
	system("date >> /var/log/korona/remote.log");
	system("echo 'reboot initiated' >> /var/log/korona/remote.log");
	system("sudo /opt/korona/bin/reboot.sh >> /var/log/korona/remote.log ");
}

function restart_service() {
	system("date >> /var/log/korona/remote.log");
	system("echo 'service restart initiated' >> /var/log/korona/remote.log");
	system("sudo /opt/korona/bin/restart_service.sh >> /var/log/korona/remote.log ");
}

function stop_service() {
	system("date >> /var/log/korona/remote.log");
	system("echo 'service stop initiated' >> /var/log/korona/remote.log");
	system("sudo /opt/korona/bin/stop_service.sh >> /var/log/korona/remote.log ");
}
