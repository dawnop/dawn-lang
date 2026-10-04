cuda_tile.module @m {
  entry @kmeans_centroid(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<i32>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %3 = make_tensor_view %2, shape = [64], strides = [1] : tensor_view<64xi32, strides=[1]>
    %4 = make_partition_view %3 : partition_view<tile=(64), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>
    %5, %6 = load_view_tko weak %4[%1] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<64xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xi32>, token
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = reshape %7 : tile<i32> -> tile<1xi32>
    %11 = broadcast %10 : tile<1xi32> -> tile<64xi32>
    %12 = cmpi equal %5, %11, signed : tile<64xi32> -> tile<64xi1>
    %13 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %16, %17 = load_view_tko weak %15[%1] token=%6 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %18 = constant <f64: 0.0> : tile<64xf64>
    %19 = select %12, %16, %18 : tile<64xi1>, tile<64xf64>
    %20 = reduce %19 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%21: tile<f64>, %22: tile<f64>) {
      %23 = addf %21, %22 rounding<nearest_even> : tile<f64>
      yield %23 : tile<f64>
    }
    %24 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %25 = make_tensor_view %24, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %26 = make_partition_view %25 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %27, %28 = load_view_tko weak %26[%1] token=%17 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %29 = select %12, %27, %18 : tile<64xi1>, tile<64xf64>
    %30 = reduce %29 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%31: tile<f64>, %32: tile<f64>) {
      %33 = addf %31, %32 rounding<nearest_even> : tile<f64>
      yield %33 : tile<f64>
    }
    %34 = constant <f64: 1.0> : tile<64xf64>
    %35 = select %12, %34, %18 : tile<64xi1>, tile<64xf64>
    %36 = reduce %35 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%37: tile<f64>, %38: tile<f64>) {
      %39 = addf %37, %38 rounding<nearest_even> : tile<f64>
      yield %39 : tile<f64>
    }
    %40 = constant <f64: 0.0> : tile<f64>
    %41 = cmpf greater_than ordered %36, %40 : tile<f64> -> tile<i1>
    %42 = constant <f64: 1.0> : tile<f64>
    %43 = select %41, %36, %42 : tile<i1>, tile<f64>
    %44 = divf %20, %43 rounding<nearest_even> : tile<f64>
    %45 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %46 = make_tensor_view %45, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %47 = make_partition_view %46 : partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %48, %49, %50 = get_tile_block_id : tile<i32>
    %51, %52 = load_view_tko weak %47[%48] token=%28 : partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1xf64>, token
    %53 = reshape %41 : tile<i1> -> tile<1xi1>
    %54 = broadcast %53 : tile<1xi1> -> tile<1xi1>
    %55 = reshape %44 : tile<f64> -> tile<1xf64>
    %56 = broadcast %55 : tile<1xf64> -> tile<1xf64>
    %57 = select %54, %56, %51 : tile<1xi1>, tile<1xf64>
    %58 = store_view_tko weak %57, %47[%48] token=%52 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %59 = divf %30, %43 rounding<nearest_even> : tile<f64>
    %60 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %61 = make_tensor_view %60, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %62 = make_partition_view %61 : partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %63, %64 = load_view_tko weak %62[%48] token=%58 : partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1xf64>, token
    %65 = reshape %59 : tile<f64> -> tile<1xf64>
    %66 = broadcast %65 : tile<1xf64> -> tile<1xf64>
    %67 = select %54, %66, %63 : tile<1xi1>, tile<1xf64>
    %68 = store_view_tko weak %67, %62[%48] token=%64 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
