cuda_tile.module @m {
  entry @grpo_adv(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 8> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <f64: 8.0> : tile<8xf64>
    %7 = reshape %5 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<8xi32>
    %9 = iota : tile<8xi32>
    %10 = addi %8, %9 : tile<8xi32>
    %11 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %12 = broadcast %11 : tile<1xptr<f64>> -> tile<8xptr<f64>>
    %13 = offset %12, %10 : tile<8xptr<f64>>, tile<8xi32> -> tile<8xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<8xptr<f64>> -> tile<8xf64>, token
    %16 = reduce %14 dim=0 identities=[0.0 : f64] : tile<8xf64> -> tile<f64> (%17: tile<f64>, %18: tile<f64>) {
      %19 = addf %17, %18 rounding<nearest_even> : tile<f64>
      yield %19 : tile<f64>
    }
    %20 = reshape %16 : tile<f64> -> tile<1xf64>
    %21 = broadcast %20 : tile<1xf64> -> tile<8xf64>
    %22 = divf %21, %6 rounding<nearest_even> : tile<8xf64>
    %23 = subf %14, %22 rounding<nearest_even> : tile<8xf64>
    %24 = mulf %23, %23 rounding<nearest_even> : tile<8xf64>
    %25 = reduce %24 dim=0 identities=[0.0 : f64] : tile<8xf64> -> tile<f64> (%26: tile<f64>, %27: tile<f64>) {
      %28 = addf %26, %27 rounding<nearest_even> : tile<f64>
      yield %28 : tile<f64>
    }
    %29 = reshape %25 : tile<f64> -> tile<1xf64>
    %30 = broadcast %29 : tile<1xf64> -> tile<8xf64>
    %31 = divf %30, %6 rounding<nearest_even> : tile<8xf64>
    %32 = sqrt %31 rounding<nearest_even> : tile<8xf64>
    %33 = constant <f64: 1.0E-8> : tile<8xf64>
    %34 = addf %32, %33 rounding<nearest_even> : tile<8xf64>
    %35 = divf %23, %34 rounding<nearest_even> : tile<8xf64>
    %36 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<8xptr<f64>>
    %38 = offset %37, %10 : tile<8xptr<f64>>, tile<8xi32> -> tile<8xptr<f64>>
    %39 = store_ptr_tko weak %38, %35 token=%15 : tile<8xptr<f64>>, tile<8xf64> -> token
    return
  }
}
