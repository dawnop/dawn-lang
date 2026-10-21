cuda_tile.module @m {
  entry @view_atomic(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<i32>>, %arg4: tile<ptr<i32>>, %arg5: tile<ptr<i32>>, %arg6: tile<ptr<i32>>, %arg7: tile<ptr<i32>>, %arg8: tile<ptr<i32>>, %arg9: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = constant <i32: 64> : tile<i32>
    %6 = muli %2, %5 : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1x1xi32>
    %8 = broadcast %7 : tile<1x1xi32> -> tile<16x64xi32>
    %9 = iota : tile<16xi32>
    %10 = reshape %9 : tile<16xi32> -> tile<16x1xi32>
    %11 = broadcast %10 : tile<16x1xi32> -> tile<16x64xi32>
    %12 = constant <i32: 0> : tile<16x64xi32>
    %13 = muli %11, %12 : tile<16x64xi32>
    %14 = addi %8, %13 : tile<16x64xi32>
    %15 = iota : tile<64xi32>
    %16 = reshape %15 : tile<64xi32> -> tile<1x64xi32>
    %17 = broadcast %16 : tile<1x64xi32> -> tile<16x64xi32>
    %18 = addi %14, %17 : tile<16x64xi32>
    %19 = constant <i32: 500> : tile<16x64xi32>
    %20 = cmpi less_than %18, %19, signed : tile<16x64xi32> -> tile<16x64xi1>
    %21 = constant <i32: -1> : tile<16x64xi32>
    %22 = reshape %arg0 : tile<ptr<i32>> -> tile<1x1xptr<i32>>
    %23 = broadcast %22 : tile<1x1xptr<i32>> -> tile<16x64xptr<i32>>
    %24 = offset %23, %18 : tile<16x64xptr<i32>>, tile<16x64xi32> -> tile<16x64xptr<i32>>
    %25, %26 = load_ptr_tko weak %24, %20, %21 token=%0 : tile<16x64xptr<i32>>, tile<16x64xi1>, tile<16x64xi32> -> tile<16x64xi32>, token
    %27 = constant <i32: 0> : tile<i32>
    %28 = reshape %27 : tile<i32> -> tile<1x1xi32>
    %29 = broadcast %28 : tile<1x1xi32> -> tile<16x64xi32>
    %30 = iota : tile<16xi32>
    %31 = reshape %30 : tile<16xi32> -> tile<16x1xi32>
    %32 = broadcast %31 : tile<16x1xi32> -> tile<16x64xi32>
    %33 = addi %29, %32 : tile<16x64xi32>
    %34 = iota : tile<64xi32>
    %35 = reshape %34 : tile<64xi32> -> tile<1x64xi32>
    %36 = broadcast %35 : tile<1x64xi32> -> tile<16x64xi32>
    %37 = constant <i32: 0> : tile<16x64xi32>
    %38 = muli %36, %37 : tile<16x64xi32>
    %39 = addi %33, %38 : tile<16x64xi32>
    %40 = cmpi equal %25, %39, signed : tile<16x64xi32> -> tile<16x64xi1>
    %41 = exti %40 unsigned : tile<16x64xi1> -> tile<16x64xi32>
    %42 = reduce %41 dim=1 identities=[0 : i32] : tile<16x64xi32> -> tile<16xi32> (%43: tile<i32>, %44: tile<i32>) {
      %45 = addi %43, %44 : tile<i32>
      yield %45 : tile<i32>
    }
    %46 = constant <i32: 3> : tile<16xi32>
    %47 = subi %42, %46 : tile<16xi32>
    %48 = constant <i32: 0> : tile<i32>
    %49 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %50 = offset %49, %48 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %51 = make_tensor_view %50, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %52 = make_partition_view %51 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %53 = atomic_red_view_tko relaxed device %52[%48], add, %42 token=%26 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %54 = constant <i32: 0> : tile<i32>
    %55 = assume div_by<16>, %arg3 : tile<ptr<i32>>
    %56 = offset %55, %54 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %57 = make_tensor_view %56, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %58 = make_partition_view %57 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %59 = atomic_red_view_tko relaxed device %58[%54], and, %47 token=%53 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %60 = constant <i32: 0> : tile<i32>
    %61 = assume div_by<16>, %arg4 : tile<ptr<i32>>
    %62 = offset %61, %60 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %63 = make_tensor_view %62, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %64 = make_partition_view %63 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %65 = atomic_red_view_tko relaxed device %64[%60], or, %47 token=%59 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %66 = constant <i32: 0> : tile<i32>
    %67 = assume div_by<16>, %arg5 : tile<ptr<i32>>
    %68 = offset %67, %66 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %69 = make_tensor_view %68, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %70 = make_partition_view %69 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %71 = atomic_red_view_tko relaxed device %70[%66], xor, %47 token=%65 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %72 = constant <i32: 0> : tile<i32>
    %73 = assume div_by<16>, %arg6 : tile<ptr<i32>>
    %74 = offset %73, %72 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %75 = make_tensor_view %74, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %76 = make_partition_view %75 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %77 = atomic_red_view_tko relaxed device %76[%72], max, %47 token=%71 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %78 = constant <i32: 0> : tile<i32>
    %79 = assume div_by<16>, %arg7 : tile<ptr<i32>>
    %80 = offset %79, %78 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %81 = make_tensor_view %80, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %82 = make_partition_view %81 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %83 = atomic_red_view_tko relaxed device %82[%78], min, %47 token=%77 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %84 = constant <i32: 0> : tile<i32>
    %85 = assume div_by<16>, %arg8 : tile<ptr<i32>>
    %86 = offset %85, %84 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %87 = make_tensor_view %86, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %88 = make_partition_view %87 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %89 = atomic_red_view_tko relaxed device %88[%84], umax, %47 token=%83 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %90 = constant <i32: 0> : tile<i32>
    %91 = assume div_by<16>, %arg9 : tile<ptr<i32>>
    %92 = offset %91, %90 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %93 = make_tensor_view %92, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %94 = make_partition_view %93 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %95 = atomic_red_view_tko relaxed device %94[%90], umin, %47 token=%89 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %96 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %97 = offset %96, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %98 = make_tensor_view %97, shape = [16], strides = [1] : tensor_view<16xf64, strides=[1]>
    %99 = make_strided_view %98 : strided_view<tile=(16), traversal_strides=[16], tensor_view<16xf64, strides=[1]>, dim_map=[0]>
    %100 = itof %42 signed rounding<nearest_even> : tile<16xi32> -> tile<16xf64>
    %101 = atomic_red_view_tko relaxed device %99[%1], addf, %100 token=%95 : tile<16xf64>, strided_view<tile=(16), traversal_strides=[16], tensor_view<16xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
