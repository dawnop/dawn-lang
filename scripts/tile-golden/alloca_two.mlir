cuda_tile.module @m {
  entry @alloca_two(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11 = alloca num_elem = 192, alignment = 8 : tile<ptr<f64>>
    %12 = reshape %11 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15 = alloca num_elem = 192, alignment = 8 global : tile<ptr<f64>>
    %16 = reshape %15 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %17 = broadcast %16 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %18 = offset %17, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %19 = reshape %5 : tile<i32> -> tile<1xi32>
    %20 = broadcast %19 : tile<1xi32> -> tile<128xi32>
    %21 = iota : tile<128xi32>
    %22 = addi %20, %21 : tile<128xi32>
    %23 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %24 = broadcast %23 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %25 = offset %24, %22 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %26, %27 = load_ptr_tko weak %25 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %28 = store_ptr_tko weak %14, %26 token=%27 : tile<128xptr<f64>>, tile<128xf64> -> token
    %29 = negf %26 : tile<128xf64>
    %30 = constant <f64: 1.0> : tile<128xf64>
    %31 = subf %29, %30 rounding<nearest_even> : tile<128xf64>
    %32 = store_ptr_tko weak %18, %31 token=%28 : tile<128xptr<f64>>, tile<128xf64> -> token
    %33, %34 = load_ptr_tko weak %14 token=%32 : tile<128xptr<f64>> -> tile<128xf64>, token
    %35, %36 = load_ptr_tko weak %18 token=%34 : tile<128xptr<f64>> -> tile<128xf64>, token
    %37 = subf %33, %35 rounding<nearest_even> : tile<128xf64>
    %38 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %39 = broadcast %38 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %40 = offset %39, %22 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %41 = store_ptr_tko weak %40, %37 token=%36 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
