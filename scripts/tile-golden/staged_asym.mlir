cuda_tile.module @m {
  entry @staged_asym(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<1xi32>
    %9 = iota : tile<1xi32>
    %10 = addi %8, %9 : tile<1xi32>
    %11 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %12 = broadcast %11 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %13 = offset %12, %10 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<1xptr<f64>> -> tile<1xf64>, token
    %16 = reduce %14 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%17: tile<f64>, %18: tile<f64>) {
      %19 = addf %17, %18 rounding<nearest_even> : tile<f64>
      yield %19 : tile<f64>
    }
    %20 = constant <f64: 0.0> : tile<f64>
    %21 = cmpf less_than ordered %16, %20 : tile<f64> -> tile<i1>
    %22 = if %21 -> (token) {
      %23 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %24 = make_tensor_view %23, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
      %25 = make_partition_view %24 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
      %26, %27, %28 = get_tile_block_id : tile<i32>
      %29, %30 = load_view_tko weak %25[%26] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %31 = constant <f64: 11.0> : tile<128xf64>
      %32 = addf %29, %31 rounding<nearest_even> : tile<128xf64>
      %33 = reshape %5 : tile<i32> -> tile<1xi32>
      %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
      %35 = iota : tile<128xi32>
      %36 = addi %34, %35 : tile<128xi32>
      %37 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %38 = broadcast %37 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %39 = offset %38, %36 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %40 = store_ptr_tko weak %39, %32 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
      yield %40 : token
    } else {
      yield %0 : token
    }
    %41 = reshape %5 : tile<i32> -> tile<1xi32>
    %42 = broadcast %41 : tile<1xi32> -> tile<128xi32>
    %43 = iota : tile<128xi32>
    %44 = addi %42, %43 : tile<128xi32>
    %45 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %46 = broadcast %45 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %47 = offset %46, %44 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %48, %49 = load_ptr_tko weak %47 token=%22 : tile<128xptr<f64>> -> tile<128xf64>, token
    %50 = constant <f64: 1.0> : tile<128xf64>
    %51 = addf %48, %50 rounding<nearest_even> : tile<128xf64>
    %52 = store_ptr_tko weak %47, %51 token=%49 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
