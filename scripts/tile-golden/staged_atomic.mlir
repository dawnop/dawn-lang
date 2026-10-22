cuda_tile.module @m {
  entry @staged_atomic(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 128> : tile<i32>
    %13 = muli %9, %12 : tile<i32>
    %14 = constant <i32: 0> : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<1xi32>
    %17 = iota : tile<1xi32>
    %18 = addi %16, %17 : tile<1xi32>
    %19 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %21 = offset %20, %18 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %22, %23 = load_ptr_tko weak %21 token=%0 : tile<1xptr<f64>> -> tile<1xf64>, token
    %24 = reduce %22 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%25: tile<f64>, %26: tile<f64>) {
      %27 = addf %25, %26 rounding<nearest_even> : tile<f64>
      yield %27 : tile<f64>
    }
    %28 = constant <f64: 0.0> : tile<f64>
    %29 = cmpf less_than ordered %24, %28 : tile<f64> -> tile<i1>
    %30, %31 = if %29 -> (tile<128xf64>, token) {
      %32 = reshape %13 : tile<i32> -> tile<1xi32>
      %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
      %34 = iota : tile<128xi32>
      %35 = addi %33, %34 : tile<128xi32>
      %36 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %37 = broadcast %36 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %38 = offset %37, %35 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %39, %40 = atomic_rmw_tko relaxed device %38, addf, %7 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> tile<128xf64>, token
      yield %39, %40 : tile<128xf64>, token
    } else {
      %41 = reshape %13 : tile<i32> -> tile<1xi32>
      %42 = broadcast %41 : tile<1xi32> -> tile<128xi32>
      %43 = iota : tile<128xi32>
      %44 = addi %42, %43 : tile<128xi32>
      %45 = constant <f64: 2.0> : tile<128xf64>
      %46 = mulf %7, %45 rounding<nearest_even> : tile<128xf64>
      %47 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %49 = offset %48, %44 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %50, %51 = atomic_rmw_tko relaxed device %49, addf, %46 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> tile<128xf64>, token
      yield %50, %51 : tile<128xf64>, token
    }
    %52 = reshape %13 : tile<i32> -> tile<1xi32>
    %53 = broadcast %52 : tile<1xi32> -> tile<128xi32>
    %54 = iota : tile<128xi32>
    %55 = addi %53, %54 : tile<128xi32>
    %56 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %57 = broadcast %56 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %58 = offset %57, %55 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %59, %60 = load_ptr_tko weak %58 token=%31 : tile<128xptr<f64>> -> tile<128xf64>, token
    %61 = addf %30, %59 rounding<nearest_even> : tile<128xf64>
    %62 = store_ptr_tko weak %58, %61 token=%60 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
