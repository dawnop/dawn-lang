cuda_tile.module @m {
  entry @dtype_tf32(%arg0: tile<ptr<tf32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<tf32>> -> tile<1xptr<tf32>>
    %13 = broadcast %12 : tile<1xptr<tf32>> -> tile<128xptr<tf32>>
    %14 = offset %13, %11 : tile<128xptr<tf32>>, tile<128xi32> -> tile<128xptr<tf32>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<tf32>> -> tile<128xtf32>, token
    %17 = ftof %15 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %18 = reshape %7 : tile<i32> -> tile<1xi32>
    %19 = broadcast %18 : tile<1xi32> -> tile<128xi32>
    %20 = iota : tile<128xi32>
    %21 = addi %19, %20 : tile<128xi32>
    %22 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %24 = offset %23, %21 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %25 = store_ptr_tko weak %24, %17 token=%16 : tile<128xptr<f64>>, tile<128xf64> -> token
    %26 = constant <i32: 512> : tile<i32>
    %27 = addi %5, %26 : tile<i32>
    %28 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %29 = broadcast %28 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %30 = offset %29, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %31, %32 = load_ptr_tko weak %30 token=%25 : tile<128xptr<f64>> -> tile<128xf64>, token
    %33 = ftof %31 rounding<nearest_even> : tile<128xf64> -> tile<128xtf32>
    %34 = ftof %33 rounding<nearest_even> : tile<128xtf32> -> tile<128xf64>
    %35 = reshape %27 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<128xi32>
    %37 = iota : tile<128xi32>
    %38 = addi %36, %37 : tile<128xi32>
    %39 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %40 = broadcast %39 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %41 = offset %40, %38 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %42 = store_ptr_tko weak %41, %34 token=%32 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
