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
    %49 = offset %arg1, %48 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %50 = make_tensor_view %49, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %51 = make_partition_view %50 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %52 = atomic_red_view_tko relaxed device %51[%48], add, %42 token=%26 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %53 = constant <i32: 0> : tile<i32>
    %54 = offset %arg3, %53 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %55 = make_tensor_view %54, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %56 = make_partition_view %55 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %57 = atomic_red_view_tko relaxed device %56[%53], and, %47 token=%52 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %58 = constant <i32: 0> : tile<i32>
    %59 = offset %arg4, %58 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %60 = make_tensor_view %59, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %61 = make_partition_view %60 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %62 = atomic_red_view_tko relaxed device %61[%58], or, %47 token=%57 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %63 = constant <i32: 0> : tile<i32>
    %64 = offset %arg5, %63 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %65 = make_tensor_view %64, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %66 = make_partition_view %65 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %67 = atomic_red_view_tko relaxed device %66[%63], xor, %47 token=%62 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %68 = constant <i32: 0> : tile<i32>
    %69 = offset %arg6, %68 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %70 = make_tensor_view %69, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %71 = make_partition_view %70 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %72 = atomic_red_view_tko relaxed device %71[%68], max, %47 token=%67 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %73 = constant <i32: 0> : tile<i32>
    %74 = offset %arg7, %73 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %75 = make_tensor_view %74, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %76 = make_partition_view %75 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %77 = atomic_red_view_tko relaxed device %76[%73], min, %47 token=%72 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %78 = constant <i32: 0> : tile<i32>
    %79 = offset %arg8, %78 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %80 = make_tensor_view %79, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %81 = make_partition_view %80 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %82 = atomic_red_view_tko relaxed device %81[%78], umax, %47 token=%77 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %83 = constant <i32: 0> : tile<i32>
    %84 = offset %arg9, %83 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %85 = make_tensor_view %84, shape = [16], strides = [1] : tensor_view<16xi32, strides=[1]>
    %86 = make_partition_view %85 : partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>
    %87 = atomic_red_view_tko relaxed device %86[%83], umin, %47 token=%82 : tile<16xi32>, partition_view<tile=(16), tensor_view<16xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %88 = offset %arg2, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %89 = make_tensor_view %88, shape = [16], strides = [1] : tensor_view<16xf64, strides=[1]>
    %90 = make_strided_view %89 : strided_view<tile=(16), traversal_strides=[16], tensor_view<16xf64, strides=[1]>, dim_map=[0]>
    %91 = itof %42 signed rounding<nearest_even> : tile<16xi32> -> tile<16xf64>
    %92 = atomic_red_view_tko relaxed device %90[%1], addf, %91 token=%87 : tile<16xf64>, strided_view<tile=(16), traversal_strides=[16], tensor_view<16xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
