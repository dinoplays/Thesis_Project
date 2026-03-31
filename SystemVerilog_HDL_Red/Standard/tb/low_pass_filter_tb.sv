`timescale 1ns/1ps

// Ensure Assignments > Settings > EDA Tool Settings > Simulation > Tool Name is "ModelSim-Altera"
// Navigate to ModelSim Altera:
//     Tool > Run Simulation Tool > RTL Simulation
// In the ModelSim Altera transcript, run:
/*
do Thesis_Project_Standard_run_lpf_tb.do
*/

module low_pass_filter_tb;

	// ------------------------------------------------------------------------
	// Clock: 50 MHz => 20 ns period
	// ------------------------------------------------------------------------
	localparam int TCLK_NS = 20;

	logic clock_50 = 1'b0;

	always #(TCLK_NS/2) clock_50 = ~clock_50;

	// ------------------------------------------------------------------------
	// Input stream paths
	// ------------------------------------------------------------------------
	localparam string IN_DIR  = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/tb/input_data";
	localparam string OUT_DIR = "/home/daniel/Thesis_Project/SystemVerilog_HDL_Red/Standard/tb/lpf_output_data";

	localparam string IN_PIXEL_MIF = {IN_DIR, "/SIM_PIXEL_BIT_DATA.mif"};
	localparam string IN_VALID_MIF = {IN_DIR, "/SIM_PIXEL_VALID_IN.mif"};
	localparam string IN_SOC_MIF   = {IN_DIR, "/SIM_SOC_IN.mif"};
	localparam string IN_EOC_MIF   = {IN_DIR, "/SIM_EOC_IN.mif"};
	localparam string IN_SOLF_MIF  = {IN_DIR, "/SIM_SOLF_IN.mif"};
	localparam string IN_EOLF_MIF  = {IN_DIR, "/SIM_EOLF_IN.mif"};

	// ------------------------------------------------------------------------
	// Stream bounds
	// ------------------------------------------------------------------------
	localparam int MAX_DEPTH = 350000;
	int DEPTH = 0;

	localparam int WARMUP_CYCLES = 16;

	// ------------------------------------------------------------------------
	// Output capture length
	// ------------------------------------------------------------------------
	localparam int EXTRA_TAIL    = 500;
	localparam int OUT_MAX_DEPTH = MAX_DEPTH + EXTRA_TAIL + 64;

	// ------------------------------------------------------------------------
	// Output MIF filenames
	// ------------------------------------------------------------------------
	localparam string OUT_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif";
	localparam string OUT_SOC_MIF   = "SIM_SOC_OUT.mif";
	localparam string OUT_EOC_MIF   = "SIM_EOC_OUT.mif";
	localparam string OUT_SOLF_MIF  = "SIM_SOLF_OUT.mif";
	localparam string OUT_EOLF_MIF  = "SIM_EOLF_OUT.mif";

	localparam string OUT_RED_MIF   = "SIM_PIXEL_OUT_RED.mif";
	localparam string OUT_GREEN_MIF = "SIM_PIXEL_OUT_GREEN.mif";
	localparam string OUT_BLUE_MIF  = "SIM_PIXEL_OUT_BLUE.mif";

	// ------------------------------------------------------------------------
	// Stimulus memories
	// ------------------------------------------------------------------------
	logic [23:0] pixel_mem [0:MAX_DEPTH-1];
	logic        valid_mem [0:MAX_DEPTH-1];
	logic        soc_mem   [0:MAX_DEPTH-1];
	logic        eoc_mem   [0:MAX_DEPTH-1];
	logic        solf_mem  [0:MAX_DEPTH-1];
	logic        eolf_mem  [0:MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Captured outputs
	// ------------------------------------------------------------------------
	logic        out_valid_mem [0:OUT_MAX_DEPTH-1];
	logic        out_soc_mem   [0:OUT_MAX_DEPTH-1];
	logic        out_eoc_mem   [0:OUT_MAX_DEPTH-1];
	logic        out_solf_mem  [0:OUT_MAX_DEPTH-1];
	logic        out_eolf_mem  [0:OUT_MAX_DEPTH-1];

	logic [14:0] out_red_mem   [0:OUT_MAX_DEPTH-1];
	logic [14:0] out_green_mem [0:OUT_MAX_DEPTH-1];
	logic [14:0] out_blue_mem  [0:OUT_MAX_DEPTH-1];

	// ------------------------------------------------------------------------
	// Driven DUT inputs
	// ------------------------------------------------------------------------
	logic [23:0] pixel_in       = 24'd0;
	logic        pixel_valid_in = 1'b0;
	logic        soc_in         = 1'b0;
	logic        eoc_in         = 1'b0;
	logic        solf_in        = 1'b0;
	logic        eolf_in        = 1'b0;

	// Split RGB for 3 DUT instances
	wire [7:0] pixel_in_red;
	wire [7:0] pixel_in_green;
	wire [7:0] pixel_in_blue;

	assign pixel_in_red   = pixel_in[23:16];
	assign pixel_in_green = pixel_in[15:8];
	assign pixel_in_blue  = pixel_in[7:0];

	// ------------------------------------------------------------------------
	// DUT outputs
	// Control is taken from RED instance
	// ------------------------------------------------------------------------
	logic        pixel_valid_out_red   = 1'b0;
	logic        soc_out_red           = 1'b0;
	logic        eoc_out_red           = 1'b0;
	logic        solf_out_red          = 1'b0;
	logic        eolf_out_red          = 1'b0;
	logic [14:0] pixel_out_red         = 15'd0;

	logic        pixel_valid_out_green = 1'b0;
	logic        soc_out_green         = 1'b0;
	logic        eoc_out_green         = 1'b0;
	logic        solf_out_green        = 1'b0;
	logic        eolf_out_green        = 1'b0;
	logic [14:0] pixel_out_green       = 15'd0;

	logic        pixel_valid_out_blue  = 1'b0;
	logic        soc_out_blue          = 1'b0;
	logic        eoc_out_blue          = 1'b0;
	logic        solf_out_blue         = 1'b0;
	logic        eolf_out_blue         = 1'b0;
	logic [14:0] pixel_out_blue        = 15'd0;

	// ------------------------------------------------------------------------
	// Image parameters
	// ------------------------------------------------------------------------
	parameter int unsigned IMAGE_DIM    = 128;

	// ------------------------------------------------------------------------
	// DUT instances
	// ------------------------------------------------------------------------
	low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM)
	) DUT_RED (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_red),
		.pixel_valid_out(pixel_valid_out_red),
		.soc_out(soc_out_red),
		.eoc_out(eoc_out_red),
		.solf_out(solf_out_red),
		.eolf_out(eolf_out_red),
		.pixel_out(pixel_out_red)
	);

	low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM)
	) DUT_GREEN (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_green),
		.pixel_valid_out(pixel_valid_out_green),
		.soc_out(soc_out_green),
		.eoc_out(eoc_out_green),
		.solf_out(solf_out_green),
		.eolf_out(eolf_out_green),
		.pixel_out(pixel_out_green)
	);

	low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM)
	) DUT_BLUE (
		.clk(clock_50),
		.pixel_valid_in(pixel_valid_in),
		.soc_in(soc_in),
		.eoc_in(eoc_in),
		.solf_in(solf_in),
		.eolf_in(eolf_in),
		.pixel_in(pixel_in_blue),
		.pixel_valid_out(pixel_valid_out_blue),
		.soc_out(soc_out_blue),
		.eoc_out(eoc_out_blue),
		.solf_out(solf_out_blue),
		.eolf_out(eolf_out_blue),
		.pixel_out(pixel_out_blue)
	);

	// Alias RED control as master control stream
	wire pixel_valid_out = pixel_valid_out_red;
	wire soc_out         = soc_out_red;
	wire eoc_out         = eoc_out_red;
	wire solf_out        = solf_out_red;
	wire eolf_out        = eolf_out_red;

	// ------------------------------------------------------------------------
	// Helper: parse DEPTH=... from MIF header
	// ------------------------------------------------------------------------
	function automatic int read_depth_from_mif(string mif_path);
		int fd;
		string line;
		int d;
		int rc;

		d  = -1;
		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF to read depth: %s", mif_path);
		end

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			rc = $sscanf(line, "DEPTH=%d;", d);
			if (rc == 1) begin
				$fclose(fd);
				return d;
			end
		end

		$fclose(fd);
		$fatal(1, "ERROR: Could not find DEPTH=... in MIF header: %s", mif_path);
		return -1;
	endfunction

	// ------------------------------------------------------------------------
	// Load MIF helpers
	// ------------------------------------------------------------------------
	task automatic load_mif_1(
		input string mif_path,
		input int depth,
		output logic mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 1'b0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);
			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 1'b0;
			rc = $sscanf(line, "%d : %b;", addr, data);
			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	task automatic load_mif_24(
		input string mif_path,
		input int depth,
		output logic [23:0] mem [0:MAX_DEPTH-1]
	);
		int fd;
		string line;
		string t1, t2;
		int rc;
		int addr;
		logic [23:0] data;
		bit in_content;

		for (int k = 0; k < MAX_DEPTH; k++) begin
			mem[k] = 24'd0;
		end

		fd = $fopen(mif_path, "r");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open MIF: %s", mif_path);
		end

		in_content = 0;

		while (!$feof(fd)) begin
			line = "";
			rc = $fgets(line, fd);
			if (rc == 0) begin
				break;
			end

			t1 = "";
			t2 = "";
			rc = $sscanf(line, "%s %s", t1, t2);
			if (!in_content) begin
				if ((rc >= 2) && (t1 == "CONTENT") && (t2 == "BEGIN")) begin
					in_content = 1;
				end
				continue;
			end

			if ((rc >= 1) && (t1 == "END;")) begin
				break;
			end

			addr = -1;
			data = 24'd0;
			rc = $sscanf(line, "%d : %b;", addr, data);
			if (rc == 2) begin
				if ((addr >= 0) && (addr < depth) && (addr < MAX_DEPTH)) begin
					mem[addr] = data;
				end
			end
		end

		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Write output MIFs
	// ------------------------------------------------------------------------
	task automatic write_mif_1(
		input string mif_path,
		input int depth,
		input logic mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=1;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %0b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	task automatic write_mif_15(
		input string mif_path,
		input int depth,
		input logic [14:0] mem [0:OUT_MAX_DEPTH-1]
	);
		int fd;

		fd = $fopen(mif_path, "w");
		if (fd == 0) begin
			$fatal(1, "ERROR: Could not open output MIF for write: %s", mif_path);
		end

		$fdisplay(fd, "WIDTH=15;");
		$fdisplay(fd, "DEPTH=%0d;", depth);
		$fdisplay(fd, "");
		$fdisplay(fd, "ADDRESS_RADIX=DEC;");
		$fdisplay(fd, "DATA_RADIX=BIN;");
		$fdisplay(fd, "");
		$fdisplay(fd, "CONTENT BEGIN");

		for (int a = 0; a < depth; a++) begin
			$fdisplay(fd, "%0d : %015b;", a, mem[a]);
		end

		$fdisplay(fd, "END;");
		$fclose(fd);
	endtask

	// ------------------------------------------------------------------------
	// Main sim
	// ------------------------------------------------------------------------
	int i;
	int out_idx;
	int OUT_DEPTH;

	initial begin
		$dumpfile("dump_lpf.vcd");
		$dumpvars(0, low_pass_filter_tb);

		DEPTH = read_depth_from_mif(IN_PIXEL_MIF);

		if (DEPTH <= 0) begin
			$fatal(1, "ERROR: DEPTH read as %0d (bad).", DEPTH);
		end

		if (DEPTH > MAX_DEPTH) begin
			$fatal(1, "ERROR: DEPTH=%0d exceeds MAX_DEPTH=%0d. Increase MAX_DEPTH.", DEPTH, MAX_DEPTH);
		end

		if ((DEPTH + WARMUP_CYCLES + EXTRA_TAIL) > OUT_MAX_DEPTH) begin
			$fatal(
				1,
				"ERROR: OUT_MAX_DEPTH too small. Need %0d but OUT_MAX_DEPTH=%0d.",
				(DEPTH + WARMUP_CYCLES + EXTRA_TAIL),
				OUT_MAX_DEPTH
			);
		end

		$display("INFO: Loading MIFs from: %s", IN_DIR);

		load_mif_24(IN_PIXEL_MIF, DEPTH, pixel_mem);
		load_mif_1 (IN_VALID_MIF, DEPTH, valid_mem);
		load_mif_1 (IN_SOC_MIF,   DEPTH, soc_mem);
		load_mif_1 (IN_EOC_MIF,   DEPTH, eoc_mem);
		load_mif_1 (IN_SOLF_MIF,  DEPTH, solf_mem);
		load_mif_1 (IN_EOLF_MIF,  DEPTH, eolf_mem);

		repeat (4) @(posedge clock_50);

		pixel_in       = 24'd0;
		pixel_valid_in = 1'b0;
		soc_in         = 1'b0;
		eoc_in         = 1'b0;
		solf_in        = 1'b0;
		eolf_in        = 1'b0;

		for (int k = 0; k < OUT_MAX_DEPTH; k++) begin
			out_valid_mem[k] = 1'b0;
			out_soc_mem[k]   = 1'b0;
			out_eoc_mem[k]   = 1'b0;
			out_solf_mem[k]  = 1'b0;
			out_eolf_mem[k]  = 1'b0;

			out_red_mem[k]   = 15'd0;
			out_green_mem[k] = 15'd0;
			out_blue_mem[k]  = 15'd0;
		end

		repeat (4) @(posedge clock_50);

		out_idx   = 0;
		OUT_DEPTH = 0;

		// Warm-up
		for (i = 0; i < WARMUP_CYCLES; i++) begin
			@(posedge clock_50);

			pixel_in       <= 24'd0;
			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		// Stimulus
		for (i = 0; i < DEPTH; i++) begin
			@(posedge clock_50);

			pixel_in       <= pixel_mem[i];
			pixel_valid_in <= valid_mem[i];
			soc_in         <= soc_mem[i];
			eoc_in         <= eoc_mem[i];
			solf_in        <= solf_mem[i];
			eolf_in        <= eolf_mem[i];

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		// Tail drain
		for (i = 0; i < EXTRA_TAIL; i++) begin
			@(posedge clock_50);

			pixel_in       <= 24'd0;
			pixel_valid_in <= 1'b0;
			soc_in         <= 1'b0;
			eoc_in         <= 1'b0;
			solf_in        <= 1'b0;
			eolf_in        <= 1'b0;

			out_valid_mem[out_idx] <= pixel_valid_out;
			out_soc_mem[out_idx]   <= soc_out;
			out_eoc_mem[out_idx]   <= eoc_out;
			out_solf_mem[out_idx]  <= solf_out;
			out_eolf_mem[out_idx]  <= eolf_out;

			out_red_mem[out_idx]   <= pixel_out_red;
			out_green_mem[out_idx] <= pixel_out_green;
			out_blue_mem[out_idx]  <= pixel_out_blue;

			out_idx <= out_idx + 1;
		end

		OUT_DEPTH = out_idx;

		$display("INFO: Writing output MIFs (OUT_DEPTH=%0d) to: %s", OUT_DEPTH, OUT_DIR);

		write_mif_1({OUT_DIR, "/", OUT_VALID_MIF}, OUT_DEPTH, out_valid_mem);
		write_mif_1({OUT_DIR, "/", OUT_SOC_MIF},   OUT_DEPTH, out_soc_mem);
		write_mif_1({OUT_DIR, "/", OUT_EOC_MIF},   OUT_DEPTH, out_eoc_mem);
		write_mif_1({OUT_DIR, "/", OUT_SOLF_MIF},  OUT_DEPTH, out_solf_mem);
		write_mif_1({OUT_DIR, "/", OUT_EOLF_MIF},  OUT_DEPTH, out_eolf_mem);

		write_mif_15({OUT_DIR, "/", OUT_RED_MIF},   OUT_DEPTH, out_red_mem);
		write_mif_15({OUT_DIR, "/", OUT_GREEN_MIF}, OUT_DEPTH, out_green_mem);
		write_mif_15({OUT_DIR, "/", OUT_BLUE_MIF},  OUT_DEPTH, out_blue_mem);

		$display("INFO: Finished. VCD = dump_lpf.vcd");
		$finish;
	end

endmodule