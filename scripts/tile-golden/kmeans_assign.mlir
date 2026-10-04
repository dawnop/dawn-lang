cuda_tile.module @m {
  entry @kmeans_assign(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5 = reshape %1 : tile<i32> -> tile<1xi32>
    %6 = broadcast %5 : tile<1xi32> -> tile<4xi32>
    %7 = iota : tile<4xi32>
    %8 = constant <i32: 0> : tile<4xi32>
    %9 = muli %7, %8 : tile<4xi32>
    %10 = addi %6, %9 : tile<4xi32>
    %11 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %12 = broadcast %11 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %13 = offset %12, %10 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<4xptr<f64>> -> tile<4xf64>, token
    %16 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %18 = make_partition_view %17 : partition_view<tile=(4), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %19, %20 = load_view_tko weak %18[%4] token=%15 : partition_view<tile=(4), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %21 = subf %14, %19 rounding<nearest_even> : tile<4xf64>
    %22 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %24 = offset %23, %10 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %25, %26 = load_ptr_tko weak %24 token=%20 : tile<4xptr<f64>> -> tile<4xf64>, token
    %27 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %28 = make_tensor_view %27, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %29 = make_partition_view %28 : partition_view<tile=(4), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %30, %31 = load_view_tko weak %29[%4] token=%26 : partition_view<tile=(4), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %32 = subf %25, %30 rounding<nearest_even> : tile<4xf64>
    %33 = mulf %21, %21 rounding<nearest_even> : tile<4xf64>
    %34 = mulf %32, %32 rounding<nearest_even> : tile<4xf64>
    %35 = addf %33, %34 rounding<nearest_even> : tile<4xf64>
    %36 = constant <i32: 0> : tile<i32>
    %37 = reshape %36 : tile<i32> -> tile<1xi32>
    %38 = broadcast %37 : tile<1xi32> -> tile<4xi32>
    %39 = iota : tile<4xi32>
    %40 = addi %38, %39 : tile<4xi32>
    %41, %42 = reduce %35, %40 dim=0 identities=[Infinity : f64, -1 : i32] : tile<4xf64>, tile<4xi32> -> tile<f64>, tile<i32> (%43: tile<f64>, %44: tile<f64>, %45: tile<i32>, %46: tile<i32>) {
      %47 = cmpf greater_than ordered %44, %43 : tile<f64> -> tile<i1>
      %48 = select %47, %43, %44 : tile<i1>, tile<f64>
      %49 = select %47, %45, %46 : tile<i1>, tile<i32>
      yield %48, %49 : tile<f64>, tile<i32>
    }
    %50 = assume div_by<16>, %arg4 : tile<ptr<i32>>
    %51 = make_tensor_view %50, shape = [64], strides = [1] : tensor_view<64xi32, strides=[1]>
    %52 = make_partition_view %51 : partition_view<tile=(1), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>
    %53, %54, %55 = get_tile_block_id : tile<i32>
    %56 = reshape %42 : tile<i32> -> tile<1xi32>
    %57 = broadcast %56 : tile<1xi32> -> tile<1xi32>
    %58 = store_view_tko weak %57, %52[%53] token=%31 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
